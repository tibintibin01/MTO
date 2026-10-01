import hashlib
import shutil
import subprocess
import zipfile

import pytest

from scripts.create_release_workflow_handoff import create_handoff, ps_literal


@pytest.fixture
def manifest():
    return {
        "version": "v2.1.99",
        "product_version": "2.1.99",
        "source_commit": "a" * 40,
        "material_hash_mode": "git-blob-sha256",
    }


def test_generated_kit_pins_release_and_tool_hashes_without_manual_attestations(
    tmp_path, manifest
):
    folder = tmp_path / "handoff"
    result = create_handoff(
        manifest, "b" * 40, folder, risk_acceptance=r"C:\mto\governance\approved.json"
    )
    assert result["status"] == "HANDOFF_CREATED_NOT_DEPLOYED"
    launcher = (folder / "Release-MTO-v2.1.99.ps1").read_text(encoding="utf-8-sig")
    batch = (folder / "Upgrade-MTO-v2.1.99.cmd").read_text(encoding="ascii")
    assert "a" * 40 in launcher
    assert "b" * 40 in launcher
    assert "InternalOnlyUnsignedRisk = $true" in launcher
    assert "--confirm-" not in launcher
    assert result["file_sha256"]["run_release_workflow.ps1"] in launcher
    assert result["file_sha256"]["Release-MTO-v2.1.99.ps1"] in batch
    assert "MTO_WORKFLOW_TOOLS=%~dp0" in batch
    assert 'choice.exe" /C 1234' in batch
    assert r"System32\WindowsPowerShell\v1.0\powershell.exe" in batch
    assert "\x0b" not in batch
    with zipfile.ZipFile(result["archive"]) as archive:
        assert set(archive.namelist()) == set(result["file_sha256"])
        assert len(archive.namelist()) == 3
        for name, digest in result["file_sha256"].items():
            assert hashlib.sha256(archive.read(name)).hexdigest().upper() == digest


def test_handoff_refuses_to_overwrite_existing_kit(tmp_path, manifest):
    create_handoff(manifest, "b" * 40, tmp_path / "kit")
    with pytest.raises(FileExistsError):
        create_handoff(manifest, "b" * 40, tmp_path / "kit")


def test_launcher_literal_escapes_apostrophe_and_rejects_injection():
    assert ps_literal("C:\\Owner's kit") == "'C:\\Owner''s kit'"
    for value in ("path\nexit", "path\rcommand", "path\0"):
        with pytest.raises(ValueError):
            ps_literal(value)


def test_generated_launcher_rejects_modified_helper_before_execution(
    tmp_path, manifest
):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell runtime required")
    folder = tmp_path / "Owner's tools"
    create_handoff(manifest, "b" * 40, folder)
    (folder / "run_release_workflow.ps1").write_text(
        "throw 'THIS MUST NEVER EXECUTE'", encoding="utf-8"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(folder / "Release-MTO-v2.1.99.ps1"),
            "-Stage",
            "Activate",
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "Workflow helper identity mismatch" in result.stderr
    assert "THIS MUST NEVER EXECUTE" not in result.stderr


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "master"),
        ("source_commit", "abc123"),
        ("product_version", "2.1.1"),
        ("material_hash_mode", "unknown"),
    ],
)
def test_bad_manifest_is_rejected_before_creating_files(
    tmp_path, manifest, field, value
):
    manifest[field] = value
    with pytest.raises(ValueError):
        create_handoff(manifest, "b" * 40, tmp_path / "kit")
    assert not (tmp_path / "kit").exists()
