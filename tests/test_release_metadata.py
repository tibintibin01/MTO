import hashlib
import json
from pathlib import Path

import pytest

from scripts import build_release_metadata as metadata


COMMIT = "a" * 40
IDENTITY = {
    "branch": "master",
    "source_commit": COMMIT,
    "release_tag": "v2.2.0",
    "product_version": "2.2.0",
    "commit_time_utc": "2026-09-17T08:00:00+00:00",
    "origin_approved": True,
    "remote_tracking_match": True,
}


def _identity_responses() -> dict[tuple[str, ...], str]:
    return {
        ("branch", "--show-current"): "master",
        ("rev-parse", "HEAD"): COMMIT,
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("remote", "get-url", "origin"): metadata.EXPECTED_ORIGIN,
        ("rev-parse", "refs/remotes/origin/master"): COMMIT,
        ("tag", "--points-at", "HEAD", "--list", "v*"): "v2.2.0",
        ("show", "-s", "--format=%cI", "HEAD"): IDENTITY["commit_time_utc"],
    }


def _git_runner(responses: dict[tuple[str, ...], str]):
    def run(_root: Path, arguments: tuple[str, ...]) -> str:
        return responses[arguments]

    return run


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_release_tree(root: Path) -> Path:
    for relative in metadata.RELEASE_MATERIALS:
        path = root / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"material:{relative}\n", encoding="utf-8")
    (root / "requirements.lock").write_text(
        "# generated with --universal\n"
        "Requests==2.34.2 \\\n"
        "    --hash=sha256:abc\n"
        "urllib3==2.6.3 \\\n"
        "    --hash=sha256:def\n",
        encoding="utf-8",
    )

    distribution = root / "dist"
    for relative in metadata.REQUIRED_ARTIFACTS:
        path = distribution / Path(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact:{relative}".encode())
    return distribution


def test_release_identity_is_derived_from_one_clean_approved_tag(tmp_path):
    result = metadata.capture_release_identity(
        tmp_path, git_runner=_git_runner(_identity_responses())
    )

    assert result == IDENTITY


def test_release_identity_normalizes_commit_time_to_utc(tmp_path):
    responses = _identity_responses()
    responses[("show", "-s", "--format=%cI", "HEAD")] = (
        "2026-09-17T16:00:00+08:00"
    )

    result = metadata.capture_release_identity(
        tmp_path, git_runner=_git_runner(responses)
    )

    assert result["commit_time_utc"] == "2026-09-17T08:00:00+00:00"


def test_prerelease_tag_is_not_accepted_for_production_installer(tmp_path):
    responses = _identity_responses()
    responses[("tag", "--points-at", "HEAD", "--list", "v*")] = "v2.2.0-rc.1"

    with pytest.raises(
        metadata.ReleaseIdentityError,
        match="SOURCE_REQUIRES_ONE_RELEASE_TAG",
    ):
        metadata.capture_release_identity(
            tmp_path, git_runner=_git_runner(responses)
        )


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        (
            ("status", "--porcelain", "--untracked-files=all"),
            " M build.py",
            "SOURCE_WORKTREE_DIRTY",
        ),
        (
            ("rev-parse", "refs/remotes/origin/master"),
            "b" * 40,
            "SOURCE_NOT_APPROVED_REMOTE_HEAD",
        ),
        (
            ("tag", "--points-at", "HEAD", "--list", "v*"),
            "v2.2.0\nv2.2.1",
            "SOURCE_REQUIRES_ONE_RELEASE_TAG",
        ),
    ],
)
def test_release_identity_fails_closed(tmp_path, key, value, code):
    responses = _identity_responses()
    responses[key] = value

    with pytest.raises(metadata.ReleaseIdentityError, match=code):
        metadata.capture_release_identity(
            tmp_path, git_runner=_git_runner(responses)
        )


def test_lock_parser_produces_sorted_cyclonedx_components(tmp_path):
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "Z_Package==2.0 \\\n    --hash=sha256:abc\n"
        "a.package==1.0 \\\n    --hash=sha256:def\n",
        encoding="utf-8",
    )

    components = metadata.parse_locked_components(lock)

    assert [item["name"] for item in components] == ["a-package", "z-package"]
    assert components[0]["purl"] == "pkg:pypi/a-package@1.0"


def test_release_metadata_is_deterministic_and_hashes_every_artifact(tmp_path):
    distribution = _write_release_tree(tmp_path)

    first = metadata.generate_release_metadata(
        root=tmp_path,
        distribution=distribution,
        identity=IDENTITY,
    )
    first_manifest = (distribution / "release-manifest.json").read_bytes()
    first_sbom = (distribution / "sbom.cdx.json").read_bytes()
    second = metadata.generate_release_metadata(
        root=tmp_path,
        distribution=distribution,
        identity=IDENTITY,
    )

    assert first_manifest == (distribution / "release-manifest.json").read_bytes()
    assert first_sbom == (distribution / "sbom.cdx.json").read_bytes()
    assert first["artifact_count"] == second["artifact_count"] == 5
    manifest = json.loads(first_manifest)
    sbom = json.loads(first_sbom)
    assert manifest["version"] == "v2.2.0"
    assert manifest["source_commit"] == COMMIT
    for relative in metadata.REQUIRED_ARTIFACTS:
        assert manifest["artifacts"][relative] == _sha256(
            distribution / Path(relative)
        )
    assert manifest["artifacts"]["sbom.cdx.json"] == _sha256(
        distribution / "sbom.cdx.json"
    )
    assert set(manifest["materials"]) == set(metadata.RELEASE_MATERIALS)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert [item["name"] for item in sbom["components"]] == [
        "requests",
        "urllib3",
    ]


def test_release_metadata_rejects_incomplete_distribution(tmp_path):
    distribution = _write_release_tree(tmp_path)
    (distribution / "installer" / "MTO_Treasury_Setup.exe").unlink()

    with pytest.raises(
        metadata.ReleaseMetadataError,
        match="REQUIRED_RELEASE_ARTIFACT_MISSING",
    ):
        metadata.generate_release_metadata(
            root=tmp_path,
            distribution=distribution,
            identity=IDENTITY,
        )


def test_release_metadata_rejects_invalid_identity_payload(tmp_path):
    distribution = _write_release_tree(tmp_path)
    invalid = {**IDENTITY, "source_commit": "not-a-commit"}

    with pytest.raises(metadata.ReleaseMetadataError, match="RELEASE_COMMIT_INVALID"):
        metadata.generate_release_metadata(
            root=tmp_path,
            distribution=distribution,
            identity=invalid,
        )


def test_release_metadata_rejects_linked_artifact_path(monkeypatch, tmp_path):
    distribution = _write_release_tree(tmp_path)
    original = metadata._is_reparse_point
    monkeypatch.setattr(
        metadata,
        "_is_reparse_point",
        lambda path: path.name == "Treasury.exe" or original(path),
    )

    with pytest.raises(metadata.ReleaseMetadataError, match="LINKED_RELEASE_PATH"):
        metadata.generate_release_metadata(
            root=tmp_path,
            distribution=distribution,
            identity=IDENTITY,
        )
