"""Generate deterministic provenance for an immutable MTO desktop release.

The release identity is derived from a clean, tagged Git commit. The final
desktop distribution receives a CycloneDX SBOM and a SHA-256 manifest covering
the executable, endpoint configuration, public CA, installer, SBOM, and the
reviewed source materials used to build them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRIMARY_BRANCH = "master"
EXPECTED_ORIGIN = "https://github.com/tibintibin01/MTO.git"
RELEASE_TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
LOCK_PATTERN = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s\\;]+)")
REQUIRED_ARTIFACTS = (
    "Treasury.exe",
    "server_config.json",
    "certificates/mto-lan-ca.pem",
    "installer/MTO_Treasury_Setup.exe",
)
RELEASE_MATERIALS = (
    "requirements.txt",
    "requirements.lock",
    "dev-requirements.txt",
    "dev-requirements.lock",
    "frontend/package.json",
    "frontend/package-lock.json",
    "Treasury.spec",
    "build_pyinstaller.ps1",
    "build_installer.ps1",
    "scripts/build_release_metadata.py",
    "scripts/verify_desktop_trust_boundary.py",
    "installer/MTO_Treasury_Setup.iss",
    ".github/workflows/deploy.yml",
)


class ReleaseIdentityError(RuntimeError):
    """The source checkout is not an approved immutable release identity."""


class ReleaseMetadataError(RuntimeError):
    """Release provenance could not be generated safely."""


def _run_git(root: Path, arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0:
        raise ReleaseIdentityError(
            f"GIT_{arguments[0].upper().replace('-', '_')}_FAILED"
        )
    return completed.stdout.strip()


def _normalize_remote(value: str) -> str:
    normalized = value.strip().replace("\\", "/").rstrip("/").lower()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def capture_release_identity(
    root: Path = PROJECT_ROOT,
    *,
    git_runner: Callable[[Path, tuple[str, ...]], str] = _run_git,
) -> dict:
    """Resolve a fail-closed release identity without contacting the network."""
    branch = git_runner(root, ("branch", "--show-current"))
    head = git_runner(root, ("rev-parse", "HEAD")).lower()
    changed = [
        line
        for line in git_runner(
            root, ("status", "--porcelain", "--untracked-files=all")
        ).splitlines()
        if line.strip()
    ]
    origin = git_runner(root, ("remote", "get-url", "origin"))
    remote_head = git_runner(
        root, ("rev-parse", f"refs/remotes/origin/{PRIMARY_BRANCH}")
    ).lower()
    tags = [
        item.strip()
        for item in git_runner(
            root, ("tag", "--points-at", "HEAD", "--list", "v*")
        ).splitlines()
        if item.strip()
    ]
    release_tags = sorted(
        tag for tag in tags if RELEASE_TAG_PATTERN.fullmatch(tag)
    )
    commit_time = git_runner(root, ("show", "-s", "--format=%cI", "HEAD"))
    try:
        commit_time_utc = (
            datetime.fromisoformat(commit_time.replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
        )
    except ValueError:
        commit_time_utc = ""

    failures: list[str] = []
    if branch not in {PRIMARY_BRANCH, ""}:
        failures.append("SOURCE_BRANCH_NOT_PRIMARY_OR_DETACHED_TAG")
    if not COMMIT_PATTERN.fullmatch(head):
        failures.append("SOURCE_COMMIT_INVALID")
    if changed:
        failures.append("SOURCE_WORKTREE_DIRTY")
    if _normalize_remote(origin) != _normalize_remote(EXPECTED_ORIGIN):
        failures.append("SOURCE_ORIGIN_UNAPPROVED")
    if head != remote_head:
        failures.append("SOURCE_NOT_APPROVED_REMOTE_HEAD")
    if len(release_tags) != 1:
        failures.append("SOURCE_REQUIRES_ONE_RELEASE_TAG")
    if not commit_time_utc:
        failures.append("SOURCE_COMMIT_TIME_MISSING")
    if failures:
        raise ReleaseIdentityError(",".join(failures))

    release_tag = release_tags[0]
    return {
        "branch": branch or "DETACHED",
        "source_commit": head,
        "release_tag": release_tag,
        "product_version": release_tag[1:],
        "commit_time_utc": commit_time_utc,
        "origin_approved": True,
        "remote_tracking_match": True,
    }


def _canonicalize_package_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_locked_components(lock_path: Path) -> list[dict]:
    """Convert a hash-locked requirements file to CycloneDX components."""
    packages: dict[str, str] = {}
    for raw_line in lock_path.read_text(encoding="utf-8").splitlines():
        match = LOCK_PATTERN.match(raw_line)
        if not match:
            continue
        name = _canonicalize_package_name(match.group(1))
        version = match.group(2)
        existing = packages.get(name)
        if existing is not None and existing != version:
            raise ReleaseMetadataError(f"LOCK_DUPLICATE_VERSION:{name}")
        packages[name] = version
    if not packages:
        raise ReleaseMetadataError("RUNTIME_LOCK_EMPTY")

    components: list[dict] = []
    for name, version in sorted(packages.items()):
        purl = f"pkg:pypi/{quote(name)}@{quote(version)}"
        components.append(
            {
                "type": "library",
                "bom-ref": purl,
                "name": name,
                "version": version,
                "purl": purl,
                "scope": "required",
            }
        )
    return components


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def _require_unlinked_path(base: Path, relative: str) -> None:
    candidate = base
    for part in Path(relative).parts:
        candidate /= part
        if candidate.exists() and _is_reparse_point(candidate):
            raise ReleaseMetadataError(f"LINKED_RELEASE_PATH:{relative}")


def _validate_identity_payload(identity: dict) -> None:
    tag = str(identity.get("release_tag") or "")
    version = str(identity.get("product_version") or "")
    commit = str(identity.get("source_commit") or "")
    commit_time = str(identity.get("commit_time_utc") or "")
    failures: list[str] = []
    if not RELEASE_TAG_PATTERN.fullmatch(tag):
        failures.append("RELEASE_TAG_INVALID")
    if version != tag.removeprefix("v"):
        failures.append("RELEASE_VERSION_MISMATCH")
    if not COMMIT_PATTERN.fullmatch(commit):
        failures.append("RELEASE_COMMIT_INVALID")
    try:
        parsed_time = datetime.fromisoformat(commit_time.replace("Z", "+00:00"))
        if parsed_time.tzinfo is None:
            failures.append("RELEASE_COMMIT_TIME_NOT_UTC")
        elif parsed_time.utcoffset() != timezone.utc.utcoffset(parsed_time):
            failures.append("RELEASE_COMMIT_TIME_NOT_UTC")
    except ValueError:
        failures.append("RELEASE_COMMIT_TIME_INVALID")
    if failures:
        raise ReleaseMetadataError(",".join(failures))


def _write_json_atomic(path: Path, payload: dict) -> Path:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, resolved)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return resolved


def _require_file(root: Path, relative: str, code: str) -> Path:
    path = root / Path(relative)
    if not path.is_file():
        raise ReleaseMetadataError(f"{code}:{relative}")
    return path


def build_cyclonedx_sbom(root: Path, identity: dict) -> dict:
    lock_path = _require_file(root, "requirements.lock", "MATERIAL_MISSING")
    components = parse_locked_components(lock_path)
    application_ref = (
        "pkg:generic/mto-treasury@" + quote(str(identity["product_version"]))
    )
    serial_seed = (
        f"mto-treasury:{identity['release_tag']}:{identity['source_commit']}"
    )
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, serial_seed)}",
        "version": 1,
        "metadata": {
            "timestamp": identity["commit_time_utc"],
            "component": {
                "type": "application",
                "bom-ref": application_ref,
                "name": "MTO Treasury System",
                "version": identity["product_version"],
                "properties": [
                    {
                        "name": "mto:release-tag",
                        "value": identity["release_tag"],
                    },
                    {
                        "name": "mto:source-commit",
                        "value": identity["source_commit"],
                    },
                ],
            },
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "name": "MTO immutable release metadata generator",
                        "version": "1",
                    }
                ]
            },
        },
        "components": components,
        "dependencies": [
            {
                "ref": application_ref,
                "dependsOn": [item["bom-ref"] for item in components],
            }
        ],
    }


def generate_release_metadata(
    *,
    root: Path,
    distribution: Path,
    identity: dict,
) -> dict:
    """Write the final SBOM and manifest after every release artifact exists."""
    if distribution.exists() and _is_reparse_point(distribution):
        raise ReleaseMetadataError("LINKED_DISTRIBUTION_ROOT")
    resolved_root = root.resolve()
    resolved_distribution = distribution.resolve()
    _validate_identity_payload(identity)
    if not resolved_distribution.is_dir():
        raise ReleaseMetadataError("DISTRIBUTION_MISSING")

    for relative in REQUIRED_ARTIFACTS:
        _require_unlinked_path(resolved_distribution, relative)
        _require_file(
            resolved_distribution,
            relative,
            "REQUIRED_RELEASE_ARTIFACT_MISSING",
        )
    for relative in RELEASE_MATERIALS:
        _require_unlinked_path(resolved_root, relative)
        _require_file(resolved_root, relative, "MATERIAL_MISSING")

    sbom_path = resolved_distribution / "sbom.cdx.json"
    sbom = build_cyclonedx_sbom(resolved_root, identity)
    _write_json_atomic(sbom_path, sbom)

    artifact_names = (*REQUIRED_ARTIFACTS, "sbom.cdx.json")
    artifacts = {
        relative: _sha256(resolved_distribution / Path(relative))
        for relative in artifact_names
    }
    materials = {
        relative: _sha256(resolved_root / Path(relative))
        for relative in RELEASE_MATERIALS
    }
    manifest = {
        "format_version": 1,
        "manifest_type": "MTO_IMMUTABLE_DESKTOP_RELEASE",
        "version": identity["release_tag"],
        "product_version": identity["product_version"],
        "source_commit": identity["source_commit"],
        "source_commit_time_utc": identity["commit_time_utc"],
        "artifacts": artifacts,
        "materials": materials,
        "sbom": {
            "path": "sbom.cdx.json",
            "format": "CycloneDX",
            "spec_version": "1.5",
            "sha256": artifacts["sbom.cdx.json"],
        },
    }
    manifest_path = resolved_distribution / "release-manifest.json"
    _write_json_atomic(manifest_path, manifest)
    return {
        "manifest_path": manifest_path,
        "sbom_path": sbom_path,
        "artifact_count": len(artifacts),
        "material_count": len(materials),
        "component_count": len(sbom["components"]),
        "version": identity["release_tag"],
        "source_commit": identity["source_commit"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--distribution", type=Path)
    parser.add_argument("--identity-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        identity = capture_release_identity(args.root)
        if args.identity_only:
            print(json.dumps(identity, sort_keys=True))
            return 0
        distribution = args.distribution or (args.root / "dist")
        result = generate_release_metadata(
            root=args.root,
            distribution=distribution,
            identity=identity,
        )
    except (OSError, ReleaseIdentityError, ReleaseMetadataError) as exc:
        print(f"IMMUTABLE RELEASE METADATA: FAIL ({exc})", file=sys.stderr)
        return 2

    print("IMMUTABLE RELEASE METADATA: PASS")
    print(f"- Version: {result['version']}")
    print(f"- Source commit: {result['source_commit'][:12]}")
    print(f"- Artifacts: {result['artifact_count']}")
    print(f"- Materials: {result['material_count']}")
    print(f"- Runtime components: {result['component_count']}")
    print(f"- Manifest: {result['manifest_path']}")
    print(f"- SBOM: {result['sbom_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
