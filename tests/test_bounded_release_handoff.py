import hashlib
import shutil
import subprocess
import zipfile

import pytest

from scripts import create_bounded_release_handoff as handoff


@pytest.fixture()
def kit_inputs(tmp_path, monkeypatch):
    paths = {}
    data = {
        "workflow_legacy_v1.ps1": b"function Legacy { 'LEGACY' }\nthrow 'NO LEGACY MAIN'\n",
        "v225_checkpoint_validation.ps1": b"function Read-Json { 'READ ONLY' }\nthrow 'NO CHECKPOINT MAIN'\n",
        "v225_acceptance_validation.ps1": b"function Assert-CompletedRecord {}\nthrow 'NO ACCEPTANCE MAIN'\n",
    }
    for name, raw in data.items():
        paths[name] = tmp_path / name
        paths[name].write_bytes(raw)
    workflow = tmp_path / "new.ps1"
    workflow.write_bytes(b"throw 'WORKFLOW MAIN MUST NOT RUN IN THIS TEST'\n")
    monkeypatch.setattr(handoff, "WORKFLOW", workflow)
    monkeypatch.setattr(handoff, "LEGACY", paths["workflow_legacy_v1.ps1"])
    monkeypatch.setattr(
        handoff, "PINNED", {name: handoff.sha(raw) for name, raw in data.items()}
    )
    return paths


def create(output, inputs, **kwargs):
    return handoff.create_handoff(
        {
            "version": "v2.1.26",
            "product_version": "2.1.26",
            "source_commit": "a" * 40,
            "material_hash_mode": "git-blob-sha256",
        },
        output,
        inputs["v225_checkpoint_validation.ps1"],
        inputs["v225_acceptance_validation.ps1"],
        **kwargs,
    )


def test_kit_pins_every_validation_helper_and_has_no_automatic_attestations(
    tmp_path, kit_inputs
):
    output = tmp_path / "kit"
    result = create(output, kit_inputs, risk_acceptance=r"C:\mto\approved.json")
    assert result["status"] == "BOUNDED_HANDOFF_CREATED_NOT_DEPLOYED"
    assert result["manual_controls_preconfirmed"] is False
    assert result["shorter_window_measured_on_office_server"] is False
    launcher = (output / "Release-MTO-v2.1.26.ps1").read_text(encoding="utf-8-sig")
    batch = (output / "Upgrade-MTO-v2.1.26.cmd").read_text(encoding="ascii")
    assert "Stage='Prepare'" in launcher
    assert "InternalOnlyUnsignedRisk=$true" in launcher
    assert "--confirm-" not in launcher
    assert 'choice.exe" /C 123456' in batch
    assert "MTO_WINDOW_STAGE=Resume" in batch
    assert "MTO_WINDOW_STAGE=Finalize" in batch
    assert result["file_sha256"]["Release-MTO-v2.1.26.ps1"] in batch
    assert "\x0b" not in batch
    for name, digest in result["file_sha256"].items():
        assert (
            hashlib.sha256((output / name).read_bytes()).hexdigest().upper() == digest
        )
    with zipfile.ZipFile(result["archive"]) as archive:
        assert set(archive.namelist()) == set(result["file_sha256"])
        assert len(archive.namelist()) == 6


def test_kit_never_overwrites_an_existing_output(tmp_path, kit_inputs):
    output = tmp_path / "kit"
    create(output, kit_inputs)
    with pytest.raises(FileExistsError):
        create(output, kit_inputs)


def test_changed_legacy_helper_blocks_before_any_output(tmp_path, kit_inputs):
    kit_inputs["v225_acceptance_validation.ps1"].write_text("changed", encoding="utf-8")
    output = tmp_path / "not-created"
    with pytest.raises(ValueError, match="helper identity changed"):
        create(output, kit_inputs)
    assert not output.exists()


def test_kit_rejects_control_characters_in_paths(tmp_path, kit_inputs):
    output = tmp_path / "not-created"
    with pytest.raises(ValueError):
        create(output, kit_inputs, distribution="C:\\bad\nthrow 'INJECTED'")
    assert not output.exists()


def test_tampered_workflow_never_runs_even_if_user_launches_activation(
    tmp_path, kit_inputs
):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    if not powershell:
        pytest.skip("PowerShell runtime required")
    output = tmp_path / "Owner's kit"
    create(output, kit_inputs)
    (output / "run_bounded_release_workflow.ps1").write_text(
        "throw 'INJECTED MAIN'", encoding="utf-8"
    )
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(output / "Release-MTO-v2.1.26.ps1"),
            "-Stage",
            "Activate",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode != 0
    assert "Release tool identity mismatch" in result.stderr
    assert "INJECTED MAIN" not in result.stderr


@pytest.mark.parametrize("version", ["v2.1.25", "v2.1.27", "master"])
def test_bounded_profile_is_not_silently_reused_for_other_releases(
    tmp_path, kit_inputs, version
):
    with pytest.raises(ValueError):
        handoff.create_handoff(
            {
                "version": version,
                "product_version": version[1:],
                "source_commit": "a" * 40,
                "material_hash_mode": "git-blob-sha256",
            },
            tmp_path / "bad",
            kit_inputs["v225_checkpoint_validation.ps1"],
            kit_inputs["v225_acceptance_validation.ps1"],
        )
    assert not (tmp_path / "bad").exists()
