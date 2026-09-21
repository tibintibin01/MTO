import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from scripts import phase5_supply_chain_preflight as preflight

APPROVED_ORIGIN = "https://github.com/tibintibin01/MTO.git"
COMMIT = "a" * 40
VERSION = preflight.PRODUCT_VERSION
RELEASE_TAG = f"v{VERSION}"


def _codes(result: dict) -> set[str]:
    return {item["code"] for item in result["findings"]}


def _git_runner(responses: dict[tuple[str, ...], str]):
    def run(_root: Path, arguments: tuple[str, ...]) -> str:
        return responses[arguments]

    return run


def _source_responses() -> dict[tuple[str, ...], str]:
    return {
        ("branch", "--show-current"): "master",
        ("rev-parse", "HEAD"): COMMIT,
        ("status", "--porcelain", "--untracked-files=all"): "",
        ("remote", "get-url", "origin"): APPROVED_ORIGIN,
        ("rev-parse", "refs/remotes/origin/master"): COMMIT,
        ("tag", "--points-at", "HEAD", "--list", "v*"): RELEASE_TAG,
    }


def _write_release_controls(root: Path, *, hardened: bool) -> None:
    workflow = root / ".github" / "workflows"
    workflow.mkdir(parents=True)
    installer_dir = root / "installer"
    installer_dir.mkdir()

    if hardened:
        deploy = """
on:
  push:
    tags: [ 'v*' ]
jobs:
  deploy:
    environment: production
    steps:
      - uses: aquasecurity/trivy-action@0123456789012345678901234567890123456789
      - run: echo ${{ github.sha }}
"""
        build = (
            "pip install --require-hashes -r dev-requirements.lock\n"
            "release-manifest.json\nsbom.cdx.json\nGet-AuthenticodeSignature\n"
        )
        installer_build = (
            "Get-AuthenticodeSignature\nbuild_release_metadata\n"
            "release-manifest.json\nsbom.cdx.json\n"
        )
        installer = (
            '#define MyAppVersion GetEnv("MTO_RELEASE_VERSION")\n'
            "SignTool=approved\nSignedUninstaller=yes\n"
        )
        updater = (
            "phase5_supply_chain_preflight\nrelease-manifest.json\n"
            "capture_remediation_baseline\nrollback\n"
            "--require-hashes -r requirements.lock\nwait_for_mto_api.ps1\n"
        )
    else:
        deploy = """
on:
  push:
    branches: [ main ]
    tags: [ 'v*' ]
jobs:
  deploy:
    environment: production
    steps:
      - uses: aquasecurity/trivy-action@0123456789012345678901234567890123456789
      - run: echo ${{ github.sha }}
"""
        build = "pyinstaller Treasury.spec\n"
        installer_build = "iscc installer\\MTO_Treasury_Setup.iss\n"
        installer = '#define MyAppVersion "2.1.0"\n'
        updater = (
            "git pull --ff-only origin master\n"
            "pip install --require-hashes -r requirements.lock\n"
            "powershell -File scripts\\wait_for_mto_api.ps1\n"
        )

    (workflow / "deploy.yml").write_text(deploy, encoding="utf-8")
    (root / "build_pyinstaller.ps1").write_text(build, encoding="utf-8")
    (root / "build_installer.ps1").write_text(installer_build, encoding="utf-8")
    (installer_dir / "MTO_Treasury_Setup.iss").write_text(installer, encoding="utf-8")
    (root / "update_mto.bat").write_text(updater, encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_release_package(root: Path) -> None:
    (root / "certificates").mkdir(parents=True)
    (root / "installer").mkdir()
    (root / "Treasury.exe").write_bytes(b"desktop-binary")
    (root / "certificates" / "mto-lan-ca.pem").write_text(
        "PUBLIC CERTIFICATE ONLY", encoding="utf-8"
    )
    (root / "installer" / "MTO_Treasury_Setup.exe").write_bytes(b"installer-binary")
    (root / "server_config.json").write_text(
        json.dumps(
            {
                "server_url": "https://WIN-6C3OM845I7L:8001",
                "ca_certificate": "certificates/mto-lan-ca.pem",
            }
        ),
        encoding="utf-8",
    )
    (root / "sbom.cdx.json").write_text(
        json.dumps(
            {
                "bomFormat": "CycloneDX",
                "specVersion": "1.5",
                "metadata": {
                    "component": {
                        "version": VERSION,
                        "properties": [{"name": "mto:source-commit", "value": COMMIT}],
                    }
                },
                "components": [{"name": "requests", "version": "2.34.2"}],
            }
        ),
        encoding="utf-8",
    )
    artifact_hashes = {
        relative: _sha256(root / Path(relative))
        for relative in preflight.REQUIRED_RELEASE_ARTIFACTS
    }
    artifact_hashes["sbom.cdx.json"] = _sha256(root / "sbom.cdx.json")
    (root / "release-manifest.json").write_text(
        json.dumps(
            {
                "version": RELEASE_TAG,
                "product_version": VERSION,
                "source_commit": COMMIT,
                "artifacts": artifact_hashes,
            }
        ),
        encoding="utf-8",
    )


def _write_risk_acceptance(root: Path, **overrides) -> Path:
    record = {
        "format_version": 1,
        "risk_id": preflight.UNSIGNED_INTERNAL_RISK_ID,
        "status": "APPROVED",
        "distribution_scope": "INTERNAL_MUNICIPAL_ONLY",
        "effective_date": "2026-09-21",
        "review_due_date": "2027-03-20",
        "approved_by_role": "MTO system owner",
        "approval_reference": "MTO-ORIGINAL-PHASE-5-EXCEPTION-2026-09-21",
        "waived_findings": sorted(preflight.UNSIGNED_INTERNAL_WAIVED_FINDINGS),
        "required_controls": sorted(preflight.UNSIGNED_INTERNAL_REQUIRED_CONTROLS),
    }
    record.update(overrides)
    path = root / "risk-acceptance.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_source_identity_passes_for_clean_tagged_remote_head(tmp_path):
    result = preflight.capture_source_identity(
        tmp_path, git_runner=_git_runner(_source_responses())
    )

    assert result["status"] == "PASS"
    assert result["commit"] == COMMIT[:12]
    assert result["release_tags"] == [RELEASE_TAG]
    assert result["findings"] == []


def test_source_identity_fails_closed_on_mutable_or_unapproved_source(tmp_path):
    responses = _source_responses()
    responses[("branch", "--show-current")] = "feature/release"
    responses[("status", "--porcelain", "--untracked-files=all")] = "?? secret.txt"
    responses[("remote", "get-url", "origin")] = "https://example.invalid/repo.git"
    responses[("rev-parse", "refs/remotes/origin/master")] = "b" * 40
    responses[("tag", "--points-at", "HEAD", "--list", "v*")] = ""

    result = preflight.capture_source_identity(
        tmp_path, git_runner=_git_runner(responses)
    )

    assert result["status"] == "FAIL"
    assert _codes(result) == {
        "SOURCE_BRANCH_NOT_PRIMARY",
        "SOURCE_WORKTREE_DIRTY",
        "SOURCE_ORIGIN_UNAPPROVED",
        "SOURCE_NOT_APPROVED_REMOTE_HEAD",
        "IMMUTABLE_RELEASE_TAG_MISSING",
    }


def test_source_identity_rejects_tag_that_differs_from_product_version(tmp_path):
    responses = _source_responses()
    responses[("tag", "--points-at", "HEAD", "--list", "v*")] = "v2.2.0"

    result = preflight.capture_source_identity(
        tmp_path, git_runner=_git_runner(responses)
    )

    assert result["status"] == "FAIL"
    assert _codes(result) == {"RELEASE_TAG_VERSION_MISMATCH"}


def test_source_identity_rejects_multiple_product_version_tags(tmp_path):
    responses = _source_responses()
    responses[("tag", "--points-at", "HEAD", "--list", "v*")] = "v2.1.0\nv2.2.0"

    result = preflight.capture_source_identity(
        tmp_path, git_runner=_git_runner(responses)
    )

    assert result["status"] == "FAIL"
    assert _codes(result) == {"IMMUTABLE_RELEASE_TAG_AMBIGUOUS"}


def test_dependency_findings_are_privacy_safe(monkeypatch, tmp_path):
    secret_path = tmp_path / "private" / "requirements.txt"
    monkeypatch.setattr(
        preflight.check_dependency_policy,
        "validate_repository",
        lambda _root: (
            [
                {
                    "code": "LOCK_MISMATCH",
                    "path": str(secret_path),
                    "detail": "Lock does not match.",
                }
            ],
            {"runtime_direct": 1},
        ),
    )

    result = preflight.capture_dependency_policy(tmp_path)

    assert result["status"] == "FAIL"
    assert str(tmp_path) not in result["findings"][0]["detail"]
    assert result["findings"][0]["detail"] == (
        "private/requirements.txt: Lock does not match."
    )


def test_release_controls_pass_when_immutable_signed_policy_is_present(tmp_path):
    _write_release_controls(tmp_path, hardened=True)

    result = preflight.capture_release_controls(tmp_path)

    assert result["status"] == "PASS"
    assert result["findings"] == []


def test_release_controls_expose_mutable_unsigned_release_gaps(tmp_path):
    _write_release_controls(tmp_path, hardened=False)

    result = preflight.capture_release_controls(tmp_path)

    assert result["status"] == "FAIL"
    assert {
        "DEPLOY_WORKFLOW_PRIMARY_BRANCH_MISMATCH",
        "PRODUCTION_RELEASE_ACCEPTS_MUTABLE_BRANCH",
        "DESKTOP_BUILD_NOT_HASH_LOCKED",
        "RELEASE_MANIFEST_NOT_GENERATED",
        "DESKTOP_SBOM_NOT_GENERATED",
        "DESKTOP_SIGNATURE_NOT_ENFORCED",
        "INSTALLER_SIGNATURE_NOT_ENFORCED",
        "INSTALLER_SIGNING_NOT_CONFIGURED",
        "INSTALLER_VERSION_STATIC",
        "UPDATER_DEPLOYS_MUTABLE_MASTER",
        "UPDATER_SUPPLY_CHAIN_GATE_MISSING",
        "UPDATER_MANIFEST_GATE_MISSING",
        "UPDATER_BASELINE_GATE_MISSING",
        "UPDATER_CODE_ROLLBACK_MISSING",
    }.issubset(_codes(result))


def test_desktop_release_passes_with_valid_signatures_manifest_and_sbom(tmp_path):
    _write_release_package(tmp_path)

    result = preflight.capture_desktop_release(
        tmp_path,
        signature_probe=lambda _path: {
            "available": True,
            "valid": True,
            "status": "Valid",
            "thumbprint_short": "ABCDEF...12345678",
        },
    )

    assert result["status"] == "PASS"
    assert result["required_artifact_count"] == 4
    assert result["sbom_valid"] is True
    assert result["sbom_identity_valid"] is True
    assert result["findings"] == []


def test_desktop_release_detects_tampering_and_private_material(tmp_path):
    _write_release_package(tmp_path)
    (tmp_path / "Treasury.exe").write_bytes(b"tampered")
    (tmp_path / "certificates" / "server-key.pem").write_text(
        "PRIVATE KEY", encoding="utf-8"
    )

    result = preflight.capture_desktop_release(
        tmp_path,
        signature_probe=lambda _path: {
            "available": True,
            "valid": False,
            "status": "NotSigned",
        },
    )

    assert result["status"] == "FAIL"
    assert {
        "RELEASE_PACKAGE_CONTAINS_PRIVATE_MATERIAL",
        "RELEASE_ARTIFACT_HASH_MISMATCH",
        "AUTHENTICODE_SIGNATURE_INVALID",
    }.issubset(_codes(result))


def test_internal_unsigned_risk_acceptance_is_explicit_and_time_bounded(tmp_path):
    path = _write_risk_acceptance(tmp_path)

    result = preflight.capture_unsigned_internal_risk_acceptance(
        path,
        distribution_scope=preflight.INTERNAL_MUNICIPAL_SCOPE,
        current_date=date(2026, 9, 21),
    )

    assert result["status"] == "PASS"
    assert result["active"] is True
    assert result["review_due_date"] == "2027-03-20"
    assert result["record_sha256"] == _sha256(path)


@pytest.mark.parametrize(
    ("scope", "overrides", "today", "code"),
    [
        (
            preflight.SIGNED_PRODUCTION_SCOPE,
            {},
            date(2026, 9, 21),
            "RISK_EXCEPTION_SCOPE_INVALID",
        ),
        (
            preflight.INTERNAL_MUNICIPAL_SCOPE,
            {"review_due_date": "2026-09-20"},
            date(2026, 9, 21),
            "RISK_ACCEPTANCE_EXPIRED",
        ),
        (
            preflight.INTERNAL_MUNICIPAL_SCOPE,
            {"review_due_date": "2027-09-21"},
            date(2026, 9, 21),
            "RISK_ACCEPTANCE_WINDOW_INVALID",
        ),
        (
            preflight.INTERNAL_MUNICIPAL_SCOPE,
            {"required_controls": []},
            date(2026, 9, 21),
            "RISK_ACCEPTANCE_CONTROLS_INCOMPLETE",
        ),
    ],
)
def test_internal_unsigned_risk_acceptance_fails_closed(
    tmp_path, scope, overrides, today, code
):
    path = _write_risk_acceptance(tmp_path, **overrides)

    result = preflight.capture_unsigned_internal_risk_acceptance(
        path, distribution_scope=scope, current_date=today
    )

    assert result["status"] == "FAIL"
    assert result["active"] is False
    assert code in _codes(result)


def test_valid_exception_waives_only_invalid_authenticode_signatures(tmp_path):
    acceptance = preflight.capture_unsigned_internal_risk_acceptance(
        _write_risk_acceptance(tmp_path),
        distribution_scope=preflight.INTERNAL_MUNICIPAL_SCOPE,
        current_date=date(2026, 9, 21),
    )
    desktop = {
        "status": "FAIL",
        "findings": [
            preflight._finding(
                "desktop_release",
                "AUTHENTICODE_SIGNATURE_INVALID",
                "Authenticode signature is not valid for Treasury.exe.",
                "HIGH",
            ),
            preflight._finding(
                "desktop_release",
                "RELEASE_ARTIFACT_HASH_MISMATCH",
                "Release artifact hash does not match Treasury.exe.",
                "CRITICAL",
            ),
        ],
    }

    result = preflight.apply_unsigned_internal_risk_exception(desktop, acceptance)

    assert result["accepted_risk_count"] == 1
    assert result["status"] == "FAIL"
    assert "AUTHENTICODE_SIGNATURE_INVALID" not in _codes(result)
    assert "AUTHENTICODE_SIGNATURE_RISK_ACCEPTED" in _codes(result)
    assert "RELEASE_ARTIFACT_HASH_MISMATCH" in _codes(result)


def test_exception_does_not_waive_unavailable_signature_verification(tmp_path):
    acceptance = preflight.capture_unsigned_internal_risk_acceptance(
        _write_risk_acceptance(tmp_path),
        distribution_scope=preflight.INTERNAL_MUNICIPAL_SCOPE,
        current_date=date(2026, 9, 21),
    )
    desktop = {
        "status": "FAIL",
        "findings": [
            preflight._finding(
                "desktop_release",
                "AUTHENTICODE_CHECK_UNAVAILABLE",
                "Authenticode verification was unavailable.",
                "HIGH",
            )
        ],
    }

    result = preflight.apply_unsigned_internal_risk_exception(desktop, acceptance)

    assert result["status"] == "FAIL"
    assert result["accepted_risk_count"] == 0
    assert "AUTHENTICODE_CHECK_UNAVAILABLE" in _codes(result)


def test_supply_chain_reports_pass_with_accepted_risk(monkeypatch, tmp_path):
    monkeypatch.setattr(
        preflight,
        "capture_source_identity",
        lambda _root: {"status": "PASS", "commit_full": COMMIT, "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_dependency_policy",
        lambda _root: {"status": "PASS", "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_release_controls",
        lambda _root: {"status": "PASS", "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_desktop_release",
        lambda *_args, **_kwargs: {
            "status": "FAIL",
            "findings": [
                preflight._finding(
                    "desktop_release",
                    "AUTHENTICODE_SIGNATURE_INVALID",
                    "Authenticode signature is not valid for Treasury.exe.",
                    "HIGH",
                ),
                preflight._finding(
                    "desktop_release",
                    "AUTHENTICODE_SIGNATURE_INVALID",
                    "Authenticode signature is not valid for MTO_Treasury_Setup.exe.",
                    "HIGH",
                ),
            ],
        },
    )

    result = preflight.capture_supply_chain(
        root=tmp_path,
        distribution=tmp_path,
        distribution_scope=preflight.INTERNAL_MUNICIPAL_SCOPE,
        risk_acceptance=_write_risk_acceptance(tmp_path),
        current_date=date(2026, 9, 21),
    )

    assert result["status"] == "PASS"
    assert result["certification_status"] == "PASS_WITH_ACCEPTED_RISK"
    assert result["accepted_risk_count"] == 2
    assert result["components"]["risk_acceptance"]["active"] is True
    assert _codes(result) == {"AUTHENTICODE_SIGNATURE_RISK_ACCEPTED"}


def test_supply_chain_rejects_expired_exception(monkeypatch, tmp_path):
    monkeypatch.setattr(
        preflight,
        "capture_source_identity",
        lambda _root: {"status": "PASS", "commit_full": COMMIT, "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_dependency_policy",
        lambda _root: {"status": "PASS", "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_release_controls",
        lambda _root: {"status": "PASS", "findings": []},
    )
    monkeypatch.setattr(
        preflight,
        "capture_desktop_release",
        lambda *_args, **_kwargs: {
            "status": "FAIL",
            "findings": [
                preflight._finding(
                    "desktop_release",
                    "AUTHENTICODE_SIGNATURE_INVALID",
                    "Authenticode signature is not valid for Treasury.exe.",
                    "HIGH",
                )
            ],
        },
    )

    result = preflight.capture_supply_chain(
        root=tmp_path,
        distribution=tmp_path,
        distribution_scope=preflight.INTERNAL_MUNICIPAL_SCOPE,
        risk_acceptance=_write_risk_acceptance(tmp_path, review_due_date="2026-09-20"),
        current_date=date(2026, 9, 21),
    )

    assert result["status"] == "FAIL"
    assert result["certification_status"] == "FAIL"
    assert result["accepted_risk_count"] == 0
    assert "AUTHENTICODE_SIGNATURE_INVALID" in _codes(result)
    assert "RISK_ACCEPTANCE_EXPIRED" in _codes(result)


def test_desktop_release_requires_manifest_and_sbom(tmp_path):
    _write_release_package(tmp_path)
    (tmp_path / "release-manifest.json").unlink()
    (tmp_path / "sbom.cdx.json").unlink()

    result = preflight.capture_desktop_release(
        tmp_path,
        signature_probe=lambda _path: {
            "available": True,
            "valid": True,
            "status": "Valid",
        },
    )

    assert result["status"] == "FAIL"
    assert "RELEASE_MANIFEST_MISSING" in _codes(result)
    assert "DESKTOP_SBOM_MISSING_OR_INVALID" in _codes(result)


def test_desktop_release_rejects_manifest_from_different_source(tmp_path):
    _write_release_package(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_commit"] = "b" * 40
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = preflight.capture_desktop_release(
        tmp_path,
        expected_source_commit=COMMIT,
        signature_probe=lambda _path: {
            "available": True,
            "valid": True,
            "status": "Valid",
        },
    )

    assert result["status"] == "FAIL"
    assert "RELEASE_MANIFEST_SOURCE_MISMATCH" in _codes(result)


def test_desktop_release_rejects_non_mapping_artifact_manifest(tmp_path):
    _write_release_package(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = preflight.capture_desktop_release(
        tmp_path,
        signature_probe=lambda _path: {
            "available": True,
            "valid": True,
            "status": "Valid",
        },
    )

    assert result["status"] == "FAIL"
    assert "RELEASE_MANIFEST_ARTIFACTS_INVALID" in _codes(result)


def test_desktop_release_rejects_sbom_from_different_source(tmp_path):
    _write_release_package(tmp_path)
    sbom_path = tmp_path / "sbom.cdx.json"
    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    sbom["metadata"]["component"]["properties"][0]["value"] = "b" * 40
    sbom_path.write_text(json.dumps(sbom), encoding="utf-8")
    manifest_path = tmp_path / "release-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["sbom.cdx.json"] = _sha256(sbom_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = preflight.capture_desktop_release(
        tmp_path,
        signature_probe=lambda _path: {
            "available": True,
            "valid": True,
            "status": "Valid",
        },
    )

    assert result["status"] == "FAIL"
    assert "DESKTOP_SBOM_IDENTITY_MISMATCH" in _codes(result)


def test_component_exception_is_redacted():
    def fail():
        raise RuntimeError("secret-token-value")

    result = preflight._capture_component("release", fail)

    assert result["status"] == "FAIL"
    assert "secret-token-value" not in json.dumps(result)
    assert "RuntimeError" in result["findings"][0]["detail"]


def test_write_report_replaces_destination_atomically(tmp_path):
    destination = tmp_path / "reports" / "phase5.json"

    resolved = preflight.write_report({"status": "PASS"}, destination)

    assert resolved == destination.resolve()
    assert json.loads(destination.read_text(encoding="utf-8")) == {"status": "PASS"}
    assert not list(destination.parent.glob("*.tmp"))


@pytest.mark.parametrize(
    ("status", "require_ready", "expected"),
    [("PASS", False, 0), ("REVIEW", False, 4), ("REVIEW", True, 2), ("FAIL", False, 2)],
)
def test_main_exit_codes(monkeypatch, tmp_path, status, require_ready, expected):
    monkeypatch.setattr(
        preflight,
        "capture_supply_chain",
        lambda **_kwargs: {
            "status": status,
            "components": {"source": {"status": status}},
            "finding_count": 0,
            "findings": [],
        },
    )
    arguments = ["--output", str(tmp_path / "report.json")]
    if require_ready:
        arguments.append("--require-ready")

    assert preflight.main(arguments) == expected
