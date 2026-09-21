import re

from scripts.phase5_supply_chain_preflight import (
    PROJECT_ROOT,
    capture_release_controls,
)


def test_production_deployment_is_tag_only():
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "deploy.yml").read_text(
        encoding="utf-8"
    )
    trigger = workflow[workflow.index("on:") : workflow.index("jobs:")]

    assert "tags: [ 'v*' ]" in trigger
    assert "branches:" not in trigger
    assert "GITHUB_REF_TYPE" in workflow
    assert "git describe --tags --exact-match HEAD" in workflow


def test_desktop_build_requires_locked_identity_and_signature():
    build = (PROJECT_ROOT / "build_pyinstaller.ps1").read_text(encoding="utf-8")

    assert "dev-requirements.lock" in build
    assert "--require-hashes" in build
    assert ".phase5-release-venv" in build
    assert "sys.version_info[:2] == (3, 11)" in build
    assert "--identity-only" in build
    assert "Get-AuthenticodeSignature" in build
    assert "MTO_CODE_SIGNING_CERT_THUMBPRINT" in build
    assert "AllowUnsignedDevelopmentBuild" in build
    assert "$releaseVersion = [string]$identity.product_version" in build
    assert "$configData.client_version = $releaseVersion" in build
    assert "Built server_config.json client_version does not match" in build


def test_installer_build_creates_final_manifest_and_sbom():
    build = (PROJECT_ROOT / "build_installer.ps1").read_text(encoding="utf-8")
    installer = (PROJECT_ROOT / "installer" / "MTO_Treasury_Setup.iss").read_text(
        encoding="utf-8"
    )

    assert "build_release_metadata.py" in build
    assert "release-manifest.json" in build
    assert "sbom.cdx.json" in build
    assert "Get-AuthenticodeSignature" in build
    assert "/DMyAppVersion=" in build
    assert re.search(r'#define\s+MyAppVersion\s+"\d+\.\d+\.\d+"', installer) is None
    assert "SignTool=MTOCodeSign" in installer
    assert "SignedUninstaller=yes" in installer


def test_installer_passes_named_arguments_to_desktop_build():
    build = (PROJECT_ROOT / "build_installer.ps1").read_text(encoding="utf-8")

    assert "$buildArguments = @{" in build
    assert "PythonPath = $Python" in build
    assert "TimestampUrl = $TimestampUrl" in build
    assert (
        '$buildArguments["SigningCertificateThumbprint"] = '
        "$SigningCertificateThumbprint" in build
    )
    assert '$buildArguments["AllowUnsignedDevelopmentBuild"] = $true' in build
    assert "& $BuildScript @buildArguments" in build
    assert '$buildArguments += @("-SigningCertificateThumbprint"' not in build


def test_release_control_preflight_passes_after_updater_hardening():
    result = capture_release_controls(PROJECT_ROOT)

    assert result["deployment_branches"] == []
    assert result["version_tag_trigger_present"] is True
    assert result["runtime_hash_install_present"] is True
    assert result["authenticated_readiness_present"] is True
    assert result["status"] == "PASS"
    assert result["findings"] == []
