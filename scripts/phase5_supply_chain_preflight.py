"""Read-only supply-chain gate for the original remediation Phase 5.

The command inspects source identity, dependency locks, release/update policy,
and an immutable desktop release package.  It never fetches source, builds or
signs artifacts, installs dependencies, starts or stops services, runs a
migration, or writes business data.  The only optional write is the requested
privacy-safe JSON report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from scripts import build_release_metadata, check_dependency_policy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRODUCT_VERSION = build_release_metadata.PRODUCT_VERSION
DEFAULT_DISTRIBUTION = PROJECT_ROOT / "dist"
DEFAULT_REPORT = (
    PROJECT_ROOT / "logs" / "remediation-original-phase-5-supply-chain.json"
)
FORMAT_VERSION = 1
REPORT_TYPE = "MTO_ORIGINAL_PHASE_5_SUPPLY_CHAIN"
PRIMARY_BRANCH = "master"
EXPECTED_ORIGIN = "https://github.com/tibintibin01/MTO.git"
RELEASE_TAG_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
REQUIRED_RELEASE_ARTIFACTS = (
    "Treasury.exe",
    "server_config.json",
    "certificates/mto-lan-ca.pem",
    "installer/MTO_Treasury_Setup.exe",
)
FORBIDDEN_ARTIFACT_SUFFIXES = frozenset({".key", ".p12", ".pfx"})
SIGNED_PRODUCTION_SCOPE = "signed-production"
INTERNAL_MUNICIPAL_SCOPE = "internal-municipal"
UNSIGNED_INTERNAL_RISK_ID = "MTO-ORIGINAL-PHASE-5-UNSIGNED-INTERNAL-ONLY"
UNSIGNED_INTERNAL_RISK_MAX_DAYS = 180
UNSIGNED_INTERNAL_WAIVED_FINDINGS = frozenset({"AUTHENTICODE_SIGNATURE_INVALID"})
UNSIGNED_INTERNAL_REQUIRED_CONTROLS = frozenset(
    {
        "CONTROLLED_INTERNAL_DISTRIBUTION",
        "IMMUTABLE_TAGGED_SOURCE",
        "MANIFEST_SHA256_VERIFICATION",
        "CYCLONEDX_SBOM",
        "MALWARE_SCAN_BEFORE_INSTALL",
        "DO_NOT_DISABLE_WINDOWS_SECURITY",
        "UNSIGNED_STATUS_DISCLOSED",
        "EXPIRING_REVIEW",
    }
)


def _finding(component: str, code: str, detail: str, severity: str) -> dict:
    return {
        "component": component,
        "code": code,
        "detail": detail,
        "severity": severity,
    }


def _status_for_findings(findings: list[dict]) -> str:
    highest = max(
        (
            SEVERITY_ORDER.get(str(item.get("severity") or "").upper(), 3)
            for item in findings
        ),
        default=0,
    )
    if highest >= SEVERITY_ORDER["HIGH"]:
        return "FAIL"
    if highest >= SEVERITY_ORDER["MEDIUM"]:
        return "REVIEW"
    return "PASS"


def _capture_component(name: str, operation: Callable[[], dict]) -> dict:
    try:
        result = operation()
    except Exception as exc:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE5_COMPONENT_CHECK_FAILED",
                    f"{name} check failed with {type(exc).__name__}.",
                    "HIGH",
                )
            ],
        }
    status = str(result.get("status") or "").upper()
    if status not in {"PASS", "REVIEW", "FAIL"}:
        return {
            "status": "FAIL",
            "findings": [
                _finding(
                    name,
                    "PHASE5_COMPONENT_STATUS_INVALID",
                    f"{name} returned an invalid supply-chain status.",
                    "HIGH",
                )
            ],
        }
    return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_remote(value: str) -> str:
    normalized = value.strip().replace("\\", "/").rstrip("/").lower()
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized


def _run_git(root: Path, arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(arguments[:2])} failed")
    return completed.stdout.strip()


def capture_source_identity(
    root: Path = PROJECT_ROOT,
    *,
    git_runner: Callable[[Path, tuple[str, ...]], str] = _run_git,
) -> dict:
    """Inspect local release identity without fetching or contacting a remote."""
    findings: list[dict] = []
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
    valid_release_tags = sorted(
        tag for tag in tags if RELEASE_TAG_PATTERN.fullmatch(tag)
    )

    if branch != PRIMARY_BRANCH:
        findings.append(
            _finding(
                "source",
                "SOURCE_BRANCH_NOT_PRIMARY",
                f"Release source must be on {PRIMARY_BRANCH}.",
                "HIGH",
            )
        )
    if changed:
        findings.append(
            _finding(
                "source",
                "SOURCE_WORKTREE_DIRTY",
                "Release source contains tracked or untracked local changes.",
                "HIGH",
            )
        )
    if _normalize_remote(origin) != _normalize_remote(EXPECTED_ORIGIN):
        findings.append(
            _finding(
                "source",
                "SOURCE_ORIGIN_UNAPPROVED",
                "The origin remote is not the approved MTO repository.",
                "CRITICAL",
            )
        )
    if not COMMIT_PATTERN.fullmatch(head) or head != remote_head:
        findings.append(
            _finding(
                "source",
                "SOURCE_NOT_APPROVED_REMOTE_HEAD",
                "The checked-out commit does not match the local approved "
                "remote-tracking head.",
                "HIGH",
            )
        )
    if not valid_release_tags:
        findings.append(
            _finding(
                "source",
                "IMMUTABLE_RELEASE_TAG_MISSING",
                "The release commit does not have an approved semantic version tag.",
                "HIGH",
            )
        )
    elif len(valid_release_tags) != 1:
        findings.append(
            _finding(
                "source",
                "IMMUTABLE_RELEASE_TAG_AMBIGUOUS",
                "The release commit has more than one production version tag.",
                "HIGH",
            )
        )
    elif valid_release_tags[0] != f"v{PRODUCT_VERSION}":
        findings.append(
            _finding(
                "source",
                "RELEASE_TAG_VERSION_MISMATCH",
                "The release tag does not match the authoritative product version.",
                "HIGH",
            )
        )

    return {
        "status": _status_for_findings(findings),
        "branch": branch,
        "commit": head[:12] if COMMIT_PATTERN.fullmatch(head) else "INVALID",
        "commit_full": head if COMMIT_PATTERN.fullmatch(head) else None,
        "changed_file_count": len(changed),
        "origin_approved": (
            _normalize_remote(origin) == _normalize_remote(EXPECTED_ORIGIN)
        ),
        "remote_tracking_match": head == remote_head,
        "release_tags": valid_release_tags,
        "product_version": PRODUCT_VERSION,
        "findings": findings,
    }


def _relative_finding_path(root: Path, value: str) -> str:
    try:
        return Path(value).resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return Path(value).name or "repository"


def capture_dependency_policy(root: Path = PROJECT_ROOT) -> dict:
    findings, counts = check_dependency_policy.validate_repository(root)
    normalized = [
        _finding(
            "dependencies",
            str(item.get("code") or "DEPENDENCY_POLICY_FAILED"),
            f"{_relative_finding_path(root, str(item.get('path') or 'repository'))}: "
            f"{str(item.get('detail') or 'Dependency policy failed.')}",
            "HIGH",
        )
        for item in findings
    ]
    return {
        "status": _status_for_findings(normalized),
        "counts": counts,
        "findings": normalized,
    }


def _read_required(path: Path, component: str, findings: list[dict]) -> str:
    if not path.is_file():
        findings.append(
            _finding(
                component,
                "RELEASE_CONTROL_FILE_MISSING",
                f"Required release control is missing: {path.name}.",
                "HIGH",
            )
        )
        return ""
    return path.read_text(encoding="utf-8")


def capture_release_controls(root: Path = PROJECT_ROOT) -> dict:
    """Inspect release, signing, and updater policy as plain source files."""
    findings: list[dict] = []
    deploy = _read_required(
        root / ".github" / "workflows" / "deploy.yml", "release_controls", findings
    )
    build = _read_required(root / "build_pyinstaller.ps1", "release_controls", findings)
    installer_build = _read_required(
        root / "build_installer.ps1", "release_controls", findings
    )
    installer = _read_required(
        root / "installer" / "MTO_Treasury_Setup.iss", "release_controls", findings
    )
    updater = _read_required(root / "update_mto.bat", "release_controls", findings)
    updater_script_path = root / "scripts" / "apply_immutable_release.ps1"
    updater_script = (
        updater_script_path.read_text(encoding="utf-8")
        if updater_script_path.is_file()
        else ""
    )
    if "apply_immutable_release.ps1" in updater.lower() and not updater_script:
        findings.append(
            _finding(
                "release_controls",
                "IMMUTABLE_UPDATER_SCRIPT_MISSING",
                "The immutable updater entry point references a missing implementation.",
                "HIGH",
            )
        )
    complete_updater = f"{updater}\n{updater_script}"
    complete_desktop_build = f"{build}\n{installer_build}"

    branch_match = re.search(r"branches:\s*\[([^\]]+)]", deploy)
    deployment_branches = (
        [
            item.strip().strip("'\"")
            for item in branch_match.group(1).split(",")
            if item.strip()
        ]
        if branch_match
        else []
    )
    if deployment_branches and PRIMARY_BRANCH not in deployment_branches:
        findings.append(
            _finding(
                "release_controls",
                "DEPLOY_WORKFLOW_PRIMARY_BRANCH_MISMATCH",
                "The deployment workflow branch trigger does not match "
                "production master.",
                "HIGH",
            )
        )
    if deployment_branches:
        findings.append(
            _finding(
                "release_controls",
                "PRODUCTION_RELEASE_ACCEPTS_MUTABLE_BRANCH",
                "Production deployment must require a reviewed version tag, "
                "not a mutable branch push.",
                "HIGH",
            )
        )
    for token, code, detail in (
        (
            "tags: [ 'v*' ]",
            "RELEASE_TAG_TRIGGER_MISSING",
            "Version-tag release triggering is missing.",
        ),
        (
            "environment: production",
            "PRODUCTION_APPROVAL_GATE_MISSING",
            "The protected production environment gate is missing.",
        ),
        (
            "trivy-action@",
            "CONTAINER_SCAN_GATE_MISSING",
            "The release workflow does not enforce a container vulnerability scan.",
        ),
        (
            "${{ github.sha }}",
            "IMMUTABLE_IMAGE_TAG_MISSING",
            "Container releases are not pinned to the source commit SHA.",
        ),
    ):
        if token not in deploy:
            findings.append(_finding("release_controls", code, detail, "HIGH"))

    if "dev-requirements.lock" not in build or "--require-hashes" not in build:
        findings.append(
            _finding(
                "release_controls",
                "DESKTOP_BUILD_NOT_HASH_LOCKED",
                "The desktop build script does not enforce the complete "
                "hash-locked build environment.",
                "HIGH",
            )
        )
    if (
        "build_release_metadata" not in installer_build
        or "release-manifest.json" not in complete_desktop_build
    ):
        findings.append(
            _finding(
                "release_controls",
                "RELEASE_MANIFEST_NOT_GENERATED",
                "The desktop build does not generate an immutable artifact manifest.",
                "HIGH",
            )
        )
    if "sbom.cdx.json" not in complete_desktop_build:
        findings.append(
            _finding(
                "release_controls",
                "DESKTOP_SBOM_NOT_GENERATED",
                "The desktop build does not generate a CycloneDX software bill "
                "of materials.",
                "MEDIUM",
            )
        )
    if "Get-AuthenticodeSignature" not in build:
        findings.append(
            _finding(
                "release_controls",
                "DESKTOP_SIGNATURE_NOT_ENFORCED",
                "The desktop build does not fail closed on an invalid "
                "Authenticode signature.",
                "HIGH",
            )
        )
    if "Get-AuthenticodeSignature" not in installer_build:
        findings.append(
            _finding(
                "release_controls",
                "INSTALLER_SIGNATURE_NOT_ENFORCED",
                "The installer build does not verify its Authenticode signature.",
                "HIGH",
            )
        )
    if "SignTool=" not in installer or "SignedUninstaller=yes" not in installer:
        findings.append(
            _finding(
                "release_controls",
                "INSTALLER_SIGNING_NOT_CONFIGURED",
                "Inno Setup signing is not configured for the installer and "
                "uninstaller.",
                "HIGH",
            )
        )
    if re.search(r'#define\s+MyAppVersion\s+"\d+\.\d+\.\d+"', installer):
        findings.append(
            _finding(
                "release_controls",
                "INSTALLER_VERSION_STATIC",
                "Installer version is static instead of being derived from the "
                "approved release identity.",
                "MEDIUM",
            )
        )

    updater_lower = complete_updater.lower()
    if "git pull --ff-only origin master" in updater_lower:
        findings.append(
            _finding(
                "release_controls",
                "UPDATER_DEPLOYS_MUTABLE_MASTER",
                "The production updater pulls mutable master directly into the "
                "active checkout.",
                "HIGH",
            )
        )
    required_updater_controls = (
        (
            "phase5_supply_chain_preflight",
            "UPDATER_SUPPLY_CHAIN_GATE_MISSING",
            "The updater does not run the approved supply-chain gate.",
        ),
        (
            "release-manifest.json",
            "UPDATER_MANIFEST_GATE_MISSING",
            "The updater does not verify an immutable release manifest.",
        ),
        (
            "capture_remediation_baseline",
            "UPDATER_BASELINE_GATE_MISSING",
            "The updater does not capture a pre-update financial baseline.",
        ),
        (
            "rollback",
            "UPDATER_CODE_ROLLBACK_MISSING",
            "The updater does not retain and exercise a code rollback path.",
        ),
    )
    for token, code, detail in required_updater_controls:
        if token not in updater_lower:
            findings.append(_finding("release_controls", code, detail, "HIGH"))
    if not all(
        token in complete_updater for token in ("--require-hashes", "requirements.lock")
    ):
        findings.append(
            _finding(
                "release_controls",
                "UPDATER_HASH_LOCK_GATE_MISSING",
                "The updater does not require the runtime dependency hashes.",
                "HIGH",
            )
        )
    if "wait_for_mto_api.ps1" not in complete_updater:
        findings.append(
            _finding(
                "release_controls",
                "UPDATER_READINESS_GATE_MISSING",
                "The updater does not require authenticated API readiness.",
                "HIGH",
            )
        )

    return {
        "status": _status_for_findings(findings),
        "deployment_branches": deployment_branches,
        "version_tag_trigger_present": "tags: [ 'v*' ]" in deploy,
        "production_approval_gate_present": "environment: production" in deploy,
        "runtime_hash_install_present": all(
            token in complete_updater
            for token in ("--require-hashes", "requirements.lock")
        ),
        "authenticated_readiness_present": ("wait_for_mto_api.ps1" in complete_updater),
        "finding_count": len(findings),
        "findings": findings,
    }


def probe_authenticode(path: Path) -> dict:
    """Return privacy-safe Windows signature metadata for one artifact."""
    if os.name != "nt":
        return {"available": False, "valid": False, "status": "UNAVAILABLE"}
    environment = os.environ.copy()
    environment["MTO_SIGNATURE_TARGET"] = str(path.resolve())
    command = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:MTO_SIGNATURE_TARGET;"
        "$c=$s.SignerCertificate;"
        "[pscustomobject]@{status=[string]$s.Status;"
        "thumbprint=if($c){[string]$c.Thumbprint}else{$null};"
        "not_after=if($c){$c.NotAfter.ToUniversalTime().ToString('o')}else{$null}}"
        "|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        return {"available": True, "valid": False, "status": "CHECK_FAILED"}
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return {"available": True, "valid": False, "status": "CHECK_FAILED"}
    thumbprint = str(payload.get("thumbprint") or "")
    return {
        "available": True,
        "valid": str(payload.get("status") or "") == "Valid",
        "status": str(payload.get("status") or "UNKNOWN"),
        "thumbprint_short": (
            f"{thumbprint[:12]}...{thumbprint[-8:]}" if len(thumbprint) >= 20 else None
        ),
        "not_after_utc": payload.get("not_after"),
    }


def _artifact_forbidden(path: Path) -> bool:
    lowered = path.name.lower()
    return (
        path.suffix.lower() in FORBIDDEN_ARTIFACT_SUFFIXES
        or "private_key" in lowered
        or lowered.endswith("-key.pem")
        or lowered.endswith("_key.pem")
    )


def capture_desktop_release(
    distribution: Path,
    *,
    signature_probe: Callable[[Path], dict] = probe_authenticode,
    source_root: Path | None = None,
    expected_source_commit: str | None = None,
    material_hash_provider: Callable[[Path, str, str], str] = (
        build_release_metadata.release_material_sha256
    ),
) -> dict:
    resolved = distribution.resolve()
    findings: list[dict] = []
    if not resolved.is_dir():
        return {
            "status": "FAIL",
            "distribution_present": False,
            "findings": [
                _finding(
                    "desktop_release",
                    "RELEASE_PACKAGE_MISSING",
                    "The immutable desktop release package is missing.",
                    "HIGH",
                )
            ],
        }

    files = [item for item in resolved.rglob("*") if item.is_file()]
    if any(_artifact_forbidden(item) for item in files):
        findings.append(
            _finding(
                "desktop_release",
                "RELEASE_PACKAGE_CONTAINS_PRIVATE_MATERIAL",
                "The desktop release package contains private-key material.",
                "CRITICAL",
            )
        )

    artifact_hashes: dict[str, str] = {}
    for relative in REQUIRED_RELEASE_ARTIFACTS:
        path = resolved / Path(relative)
        if not path.is_file():
            findings.append(
                _finding(
                    "desktop_release",
                    "REQUIRED_RELEASE_ARTIFACT_MISSING",
                    f"Required release artifact is missing: {relative}.",
                    "HIGH",
                )
            )
        else:
            artifact_hashes[relative] = _sha256(path)

    config_path = resolved / "server_config.json"
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            config = {}
        if not str(config.get("server_url") or "").startswith("https://"):
            findings.append(
                _finding(
                    "desktop_release",
                    "DESKTOP_HTTPS_CONFIGURATION_INVALID",
                    "Desktop release configuration must use HTTPS.",
                    "CRITICAL",
                )
            )
        if config.get("ca_certificate") != "certificates/mto-lan-ca.pem":
            findings.append(
                _finding(
                    "desktop_release",
                    "DESKTOP_CA_CONFIGURATION_INVALID",
                    "Desktop release configuration must reference the packaged "
                    "public CA.",
                    "CRITICAL",
                )
            )

    signatures: dict[str, dict] = {}
    for relative in ("Treasury.exe", "installer/MTO_Treasury_Setup.exe"):
        path = resolved / Path(relative)
        if not path.is_file():
            continue
        signature = signature_probe(path)
        signatures[relative] = signature
        if not signature.get("available"):
            findings.append(
                _finding(
                    "desktop_release",
                    "AUTHENTICODE_CHECK_UNAVAILABLE",
                    f"Authenticode could not be checked for {relative}.",
                    "HIGH",
                )
            )
        elif not signature.get("valid"):
            findings.append(
                _finding(
                    "desktop_release",
                    "AUTHENTICODE_SIGNATURE_INVALID",
                    f"Authenticode signature is not valid for {relative}.",
                    "HIGH",
                )
            )

    manifest_path = resolved / "release-manifest.json"
    manifest_version = None
    manifest_commit = None
    manifest: dict = {}
    if not manifest_path.is_file():
        findings.append(
            _finding(
                "desktop_release",
                "RELEASE_MANIFEST_MISSING",
                "The immutable release manifest is missing.",
                "HIGH",
            )
        )
    else:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_MANIFEST_STRUCTURE_INVALID",
                    "Release manifest must be a JSON object.",
                    "HIGH",
                )
            )
        manifest_version = str(manifest.get("version") or "")
        manifest_commit = str(manifest.get("source_commit") or "").lower()
        listed = manifest.get("artifacts")
        if listed is None:
            listed = {}
        if not isinstance(listed, dict):
            listed = {}
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_MANIFEST_ARTIFACTS_INVALID",
                    "Release manifest artifacts must be a hash mapping.",
                    "HIGH",
                )
            )
        if not RELEASE_TAG_PATTERN.fullmatch(manifest_version):
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_MANIFEST_VERSION_INVALID",
                    "Release manifest version is not an approved semantic version tag.",
                    "HIGH",
                )
            )
        if not COMMIT_PATTERN.fullmatch(manifest_commit):
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_MANIFEST_COMMIT_INVALID",
                    "Release manifest source commit is invalid.",
                    "HIGH",
                )
            )
        if (
            expected_source_commit
            and COMMIT_PATTERN.fullmatch(expected_source_commit)
            and manifest_commit != expected_source_commit
        ):
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_MANIFEST_SOURCE_MISMATCH",
                    "Release manifest source does not match the approved checkout.",
                    "CRITICAL",
                )
            )
        for relative, actual_hash in artifact_hashes.items():
            recorded_hash = str(listed.get(relative) or "").lower()
            if recorded_hash != actual_hash:
                findings.append(
                    _finding(
                        "desktop_release",
                        "RELEASE_ARTIFACT_HASH_MISMATCH",
                        f"Release manifest hash does not match {relative}.",
                        "CRITICAL",
                    )
                )
        if source_root is not None:
            materials = manifest.get("materials")
            if materials is None:
                materials = {}
            if not isinstance(materials, dict):
                materials = {}
            material_hash_mode = str(manifest.get("material_hash_mode") or "")
            if material_hash_mode != build_release_metadata.MATERIAL_HASH_MODE:
                findings.append(
                    _finding(
                        "desktop_release",
                        "RELEASE_MATERIAL_HASH_MODE_INVALID",
                        "Release materials must use immutable Git-blob SHA-256 hashes.",
                        "CRITICAL",
                    )
                )
            elif COMMIT_PATTERN.fullmatch(manifest_commit):
                for relative in build_release_metadata.RELEASE_MATERIALS:
                    recorded_hash = str(materials.get(relative) or "").lower()
                    try:
                        actual_hash = material_hash_provider(
                            source_root.resolve(),
                            manifest_commit,
                            relative,
                        )
                    except (OSError, RuntimeError, subprocess.SubprocessError):
                        actual_hash = None
                    if recorded_hash == actual_hash:
                        continue
                    findings.append(
                        _finding(
                            "desktop_release",
                            "RELEASE_MATERIAL_HASH_MISMATCH",
                            f"Release material hash does not match {relative}.",
                            "CRITICAL",
                        )
                    )

    sbom_path = resolved / "sbom.cdx.json"
    sbom_valid = False
    sbom_identity_valid = False
    if sbom_path.is_file():
        try:
            sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
            if not isinstance(sbom, dict):
                sbom = {}
            sbom_components = sbom.get("components")
            sbom_valid = (
                sbom.get("bomFormat") == "CycloneDX"
                and bool(sbom.get("specVersion"))
                and isinstance(sbom_components, list)
                and bool(sbom_components)
            )
            sbom_metadata = sbom.get("metadata")
            sbom_application = (
                sbom_metadata.get("component", {})
                if isinstance(sbom_metadata, dict)
                else {}
            )
            if not isinstance(sbom_application, dict):
                sbom_application = {}
            sbom_properties = {
                str(item.get("name") or ""): str(item.get("value") or "")
                for item in sbom_application.get("properties", [])
                if isinstance(item, dict)
            }
            sbom_identity_valid = (
                str(sbom_application.get("version") or "")
                == str(manifest.get("product_version") or "")
                and sbom_properties.get("mto:source-commit") == manifest_commit
            )
        except (OSError, json.JSONDecodeError):
            sbom_valid = False
    if not sbom_valid:
        findings.append(
            _finding(
                "desktop_release",
                "DESKTOP_SBOM_MISSING_OR_INVALID",
                "The CycloneDX desktop SBOM is missing or invalid.",
                "MEDIUM",
            )
        )
    elif manifest_path.is_file() and not sbom_identity_valid:
        findings.append(
            _finding(
                "desktop_release",
                "DESKTOP_SBOM_IDENTITY_MISMATCH",
                "CycloneDX SBOM identity does not match the release manifest.",
                "HIGH",
            )
        )
    if sbom_valid and manifest_path.is_file():
        listed = manifest.get("artifacts")
        if listed is None:
            listed = {}
        recorded_sbom_hash = (
            str(listed.get("sbom.cdx.json") or "").lower()
            if isinstance(listed, dict)
            else ""
        )
        if recorded_sbom_hash != _sha256(sbom_path):
            findings.append(
                _finding(
                    "desktop_release",
                    "RELEASE_SBOM_HASH_MISMATCH",
                    "Release manifest hash does not match the CycloneDX SBOM.",
                    "CRITICAL",
                )
            )

    return {
        "status": _status_for_findings(findings),
        "distribution_present": True,
        "file_count": len(files),
        "required_artifact_count": len(artifact_hashes),
        "artifact_hashes": artifact_hashes,
        "signatures": signatures,
        "manifest": {
            "present": manifest_path.is_file(),
            "version": manifest_version,
            "source_commit": (
                manifest_commit[:12]
                if manifest_commit and COMMIT_PATTERN.fullmatch(manifest_commit)
                else None
            ),
        },
        "sbom_valid": sbom_valid,
        "sbom_identity_valid": sbom_identity_valid,
        "findings": findings,
    }


def capture_unsigned_internal_risk_acceptance(
    path: Path | None,
    *,
    distribution_scope: str,
    current_date: date | None = None,
) -> dict:
    """Validate the narrow, expiring unsigned internal-release exception."""
    findings: list[dict] = []
    resolved = path.resolve() if path is not None else None
    record: dict = {}

    if distribution_scope != INTERNAL_MUNICIPAL_SCOPE:
        findings.append(
            _finding(
                "risk_acceptance",
                "RISK_EXCEPTION_SCOPE_INVALID",
                "The unsigned exception is valid only for internal municipal distribution.",
                "HIGH",
            )
        )
    if resolved is None or not resolved.is_file():
        findings.append(
            _finding(
                "risk_acceptance",
                "RISK_ACCEPTANCE_RECORD_MISSING",
                "The explicit unsigned internal-only risk acceptance record is missing.",
                "HIGH",
            )
        )
    else:
        try:
            loaded = json.loads(resolved.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                record = loaded
            else:
                raise ValueError("record must be an object")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            findings.append(
                _finding(
                    "risk_acceptance",
                    "RISK_ACCEPTANCE_RECORD_INVALID",
                    "The risk acceptance record is not valid JSON governance data.",
                    "HIGH",
                )
            )

    effective: date | None = None
    review_due: date | None = None
    if record:
        expected_values = {
            "format_version": 1,
            "risk_id": UNSIGNED_INTERNAL_RISK_ID,
            "status": "APPROVED",
            "distribution_scope": "INTERNAL_MUNICIPAL_ONLY",
        }
        for field, expected in expected_values.items():
            if record.get(field) != expected:
                findings.append(
                    _finding(
                        "risk_acceptance",
                        "RISK_ACCEPTANCE_IDENTITY_INVALID",
                        f"Risk acceptance field {field} does not match the approved policy.",
                        "HIGH",
                    )
                )

        try:
            effective = date.fromisoformat(str(record.get("effective_date") or ""))
            review_due = date.fromisoformat(str(record.get("review_due_date") or ""))
        except ValueError:
            findings.append(
                _finding(
                    "risk_acceptance",
                    "RISK_ACCEPTANCE_DATES_INVALID",
                    "Risk acceptance effective and review dates must use ISO dates.",
                    "HIGH",
                )
            )
        if effective is not None and review_due is not None:
            duration = (review_due - effective).days
            today = current_date or datetime.now(timezone.utc).date()
            if duration <= 0 or duration > UNSIGNED_INTERNAL_RISK_MAX_DAYS:
                findings.append(
                    _finding(
                        "risk_acceptance",
                        "RISK_ACCEPTANCE_WINDOW_INVALID",
                        "The unsigned exception must expire within 180 days.",
                        "HIGH",
                    )
                )
            if today < effective:
                findings.append(
                    _finding(
                        "risk_acceptance",
                        "RISK_ACCEPTANCE_NOT_YET_EFFECTIVE",
                        "The unsigned exception is not yet effective.",
                        "HIGH",
                    )
                )
            if today > review_due:
                findings.append(
                    _finding(
                        "risk_acceptance",
                        "RISK_ACCEPTANCE_EXPIRED",
                        "The unsigned internal-only exception has expired.",
                        "HIGH",
                    )
                )

        waived = record.get("waived_findings")
        if not isinstance(waived, list) or set(map(str, waived)) != set(
            UNSIGNED_INTERNAL_WAIVED_FINDINGS
        ):
            findings.append(
                _finding(
                    "risk_acceptance",
                    "RISK_ACCEPTANCE_WAIVER_INVALID",
                    "The record may waive only invalid Authenticode signatures.",
                    "HIGH",
                )
            )
        controls = record.get("required_controls")
        if not isinstance(
            controls, list
        ) or not UNSIGNED_INTERNAL_REQUIRED_CONTROLS.issubset(set(map(str, controls))):
            findings.append(
                _finding(
                    "risk_acceptance",
                    "RISK_ACCEPTANCE_CONTROLS_INCOMPLETE",
                    "The record does not require every compensating control.",
                    "HIGH",
                )
            )
        role = str(record.get("approved_by_role") or "").strip()
        reference = str(record.get("approval_reference") or "").strip()
        if (
            not role
            or len(role) > 80
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9._:-]{7,100}", reference)
        ):
            findings.append(
                _finding(
                    "risk_acceptance",
                    "RISK_ACCEPTANCE_APPROVAL_INVALID",
                    "The approving role or approval reference is missing or invalid.",
                    "HIGH",
                )
            )

    active = not findings
    return {
        "status": "PASS" if active else "FAIL",
        "active": active,
        "risk_id": (
            UNSIGNED_INTERNAL_RISK_ID
            if record.get("risk_id") == UNSIGNED_INTERNAL_RISK_ID
            else None
        ),
        "record_sha256": _sha256(resolved) if resolved and resolved.is_file() else None,
        "effective_date": effective.isoformat() if effective else None,
        "review_due_date": review_due.isoformat() if review_due else None,
        "waived_findings": sorted(UNSIGNED_INTERNAL_WAIVED_FINDINGS) if active else [],
        "required_control_count": (
            len(UNSIGNED_INTERNAL_REQUIRED_CONTROLS) if active else 0
        ),
        "findings": findings,
    }


def apply_unsigned_internal_risk_exception(
    desktop_release: dict, risk_acceptance: dict
) -> dict:
    """Accept only unsigned-artifact findings under a validated exception."""
    result = dict(desktop_release)
    findings = list(desktop_release.get("findings") or [])
    if not risk_acceptance.get("active"):
        result["accepted_findings"] = []
        result["accepted_risk_count"] = 0
        return result

    retained: list[dict] = []
    accepted: list[dict] = []
    for item in findings:
        if (
            str(item.get("component") or "") == "desktop_release"
            and str(item.get("code") or "") in UNSIGNED_INTERNAL_WAIVED_FINDINGS
        ):
            accepted.append(
                {
                    "code": str(item.get("code")),
                    "detail": str(item.get("detail") or "Unsigned artifact."),
                }
            )
        else:
            retained.append(item)

    if accepted:
        retained.append(
            _finding(
                "desktop_release",
                "AUTHENTICODE_SIGNATURE_RISK_ACCEPTED",
                "Unsigned executable and installer artifacts are accepted only for "
                f"controlled internal municipal use through {risk_acceptance['review_due_date']}.",
                "LOW",
            )
        )
    result["findings"] = retained
    result["status"] = _status_for_findings(retained)
    result["accepted_findings"] = accepted
    result["accepted_risk_count"] = len(accepted)
    return result


def _normalized_findings(components: dict[str, dict]) -> list[dict]:
    normalized: list[dict] = []
    for component_name, component in components.items():
        findings = component.get("findings") or []
        for item in findings:
            normalized.append(
                {
                    "component": str(item.get("component") or component_name),
                    "code": str(item.get("code") or "PHASE5_SUPPLY_CHAIN_FINDING"),
                    "detail": str(
                        item.get("detail") or "Supply-chain review is required."
                    ),
                    "severity": str(item.get("severity") or "HIGH").upper(),
                }
            )
        if str(component.get("status") or "").upper() == "FAIL" and not findings:
            normalized.append(
                _finding(
                    component_name,
                    "PHASE5_COMPONENT_FAILED",
                    f"{component_name} failed without a diagnostic finding.",
                    "HIGH",
                )
            )
    return normalized


def summarize_components(components: dict[str, dict]) -> tuple[str, list[dict]]:
    findings = _normalized_findings(components)
    statuses = {
        str(component.get("status") or "FAIL").upper()
        for component in components.values()
    }
    status = _status_for_findings(findings)
    if "FAIL" in statuses:
        status = "FAIL"
    elif status == "PASS" and "REVIEW" in statuses:
        status = "REVIEW"
    return status, findings


def capture_supply_chain(
    *,
    root: Path = PROJECT_ROOT,
    distribution: Path = DEFAULT_DISTRIBUTION,
    distribution_scope: str = SIGNED_PRODUCTION_SCOPE,
    risk_acceptance: Path | None = None,
    current_date: date | None = None,
) -> dict:
    source = _capture_component("source", lambda: capture_source_identity(root))
    components = {
        "source": source,
        "dependencies": _capture_component(
            "dependencies", lambda: capture_dependency_policy(root)
        ),
        "release_controls": _capture_component(
            "release_controls", lambda: capture_release_controls(root)
        ),
        "desktop_release": _capture_component(
            "desktop_release",
            lambda: capture_desktop_release(
                distribution,
                source_root=root,
                expected_source_commit=source.get("commit_full"),
            ),
        ),
    }
    if risk_acceptance is not None or distribution_scope == INTERNAL_MUNICIPAL_SCOPE:
        acceptance = _capture_component(
            "risk_acceptance",
            lambda: capture_unsigned_internal_risk_acceptance(
                risk_acceptance,
                distribution_scope=distribution_scope,
                current_date=current_date,
            ),
        )
        components["risk_acceptance"] = acceptance
        components["desktop_release"] = apply_unsigned_internal_risk_exception(
            components["desktop_release"], acceptance
        )
    status, findings = summarize_components(components)
    accepted_risk_count = int(
        components["desktop_release"].get("accepted_risk_count") or 0
    )
    certification_status = (
        "PASS_WITH_ACCEPTED_RISK"
        if status == "PASS" and accepted_risk_count
        else status
    )
    return {
        "format_version": FORMAT_VERSION,
        "report_type": REPORT_TYPE,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "certification_status": certification_status,
        "distribution_scope": distribution_scope,
        "components": components,
        "finding_count": len(findings),
        "findings": findings,
        "accepted_risk_count": accepted_risk_count,
    }


def write_report(report: dict, destination: Path) -> Path:
    resolved = destination.resolve()
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
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, resolved)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the read-only original Phase 5 supply-chain gate."
    )
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="Require every source, dependency, release, and artifact gate to pass.",
    )
    parser.add_argument("--distribution", type=Path, default=DEFAULT_DISTRIBUTION)
    parser.add_argument(
        "--distribution-scope",
        choices=(SIGNED_PRODUCTION_SCOPE, INTERNAL_MUNICIPAL_SCOPE),
        default=SIGNED_PRODUCTION_SCOPE,
        help="Use internal-municipal only with an explicitly approved risk record.",
    )
    parser.add_argument(
        "--risk-acceptance",
        type=Path,
        help="Validated, expiring governance record for an unsigned internal release.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    report = capture_supply_chain(
        distribution=args.distribution,
        distribution_scope=args.distribution_scope,
        risk_acceptance=args.risk_acceptance,
    )
    report["require_ready"] = bool(args.require_ready)
    destination = write_report(report, args.output)

    print("ORIGINAL PHASE 5 SUPPLY-CHAIN PREFLIGHT")
    for name, component in report["components"].items():
        print(f"- {name}: {component['status']}")
    print(f"- Gate status: {report['status']}")
    print(
        f"- Certification status: "
        f"{report.get('certification_status', report['status'])}"
    )
    print(
        f"- Distribution scope: {report.get('distribution_scope', SIGNED_PRODUCTION_SCOPE)}"
    )
    print(f"- Accepted risk findings: {report.get('accepted_risk_count', 0)}")
    print(f"- Findings: {report['finding_count']}")
    print(f"- Privacy-safe report: {destination}")
    for item in report["findings"]:
        print(
            f"  - [{item['severity']}] {item['component']}/{item['code']}: "
            f"{item['detail']}"
        )

    if report["status"] == "PASS":
        print("  ORIGINAL PHASE 5 SUPPLY-CHAIN PREFLIGHT PASSED")
        return 0
    if report["status"] == "REVIEW" and not args.require_ready:
        print("  ORIGINAL PHASE 5 SUPPLY-CHAIN PREFLIGHT REQUIRES REVIEW")
        return 4
    print("  ORIGINAL PHASE 5 SUPPLY-CHAIN PREFLIGHT BLOCKED")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
