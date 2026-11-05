"""Create a v2.1.26 short-window launcher kit; never activate production."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from scripts.create_release_workflow_handoff import COMMIT_PATTERN, ps_literal

WORKFLOW = Path(__file__).with_name("run_bounded_release_workflow.ps1")
LEGACY = Path(__file__).with_name("run_release_workflow.ps1")
PREVIOUS = "2e4fabdd10efab6350dea2f77029f08909f61af0"
PINNED = {
    "workflow_legacy_v1.ps1": "EFD7761A37EE99A2B510B3D5A2BEA306B1F2FFF6D74F1B7E6C41EA2B4830DC67",
    "v225_checkpoint_validation.ps1": "ECD80D3635AE9D049CD5174E766B2DD7A3366D3672954C258F4EA849109FB67F",
    "v225_acceptance_validation.ps1": "74380889C60D38D2CEFFBAEE752DD16C2030AE787C1490A5CFB60B74D30AEF24",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def pinned_legacy_bytes(path: Path) -> bytes:
    """Recover exact already-approved Windows bytes from a Linux LF checkout."""
    raw = path.read_bytes()
    if sha(raw) == PINNED["workflow_legacy_v1.ps1"]:
        return raw
    windows = raw.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    if sha(windows) != PINNED["workflow_legacy_v1.ps1"]:
        raise ValueError(
            "The unchanged legacy workflow does not match its approved pin"
        )
    return windows


def create_handoff(
    manifest: dict,
    output: Path,
    checkpoint_validation: Path,
    acceptance_validation: Path,
    *,
    distribution: str = r"C:\ProgramData\MTO\releases\v2.1.26",
    project_root: str = r"C:\mto",
    risk_acceptance: str | None = None,
) -> dict:
    commit = str(manifest.get("source_commit") or "")
    if (
        manifest.get("version") != "v2.1.26"
        or manifest.get("product_version") != "2.1.26"
        or manifest.get("material_hash_mode") != "git-blob-sha256"
        or not COMMIT_PATTERN.fullmatch(commit)
        or commit == PREVIOUS
    ):
        raise ValueError("Exact v2.1.26 immutable manifest required")
    files = {
        "run_bounded_release_workflow.ps1": WORKFLOW.read_bytes(),
        "workflow_legacy_v1.ps1": pinned_legacy_bytes(LEGACY),
        "v225_checkpoint_validation.ps1": checkpoint_validation.read_bytes(),
        "v225_acceptance_validation.ps1": acceptance_validation.read_bytes(),
    }
    for name, digest in PINNED.items():
        if sha(files[name]) != digest:
            raise ValueError("Existing validated helper identity changed: " + name)
    checks = "\n".join(
        f"if((Get-ToolHash (Join-Path $PSScriptRoot {ps_literal(name)})) -cne '{sha(data)}'){{throw 'Release tool identity mismatch'}}"
        for name, data in files.items()
    )
    arguments = {
        "ReleaseTag": "v2.1.26",
        "ExpectedCommit": commit,
        "PreviousCommit": PREVIOUS,
        "Distribution": distribution,
        "ProjectRoot": project_root,
    }
    parameters = "\n".join(
        f"    {key}={ps_literal(value)}" for key, value in arguments.items()
    )
    if risk_acceptance:
        parameters += (
            "\n    InternalOnlyUnsignedRisk=$true\n    RiskAcceptance="
            + ps_literal(risk_acceptance)
        )
    launcher = f"""# Hash-pinned bounded-window release. No automatic attestations.
param([ValidateSet('Prepare','Activate','Verify','Resume','Finalize')][string]$Stage='Prepare')
$ErrorActionPreference='Stop'
function Get-ToolHash {{
    param([string]$Path)
    $sha=[Security.Cryptography.SHA256]::Create();$stream=$null
    try{{$stream=[IO.File]::OpenRead($Path);return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','')}}
    finally{{if($stream){{$stream.Dispose()}};$sha.Dispose()}}
}}
{checks}
$parameters=@{{
{parameters}
}}
if($Stage -cne 'Prepare'){{
    $identity=([string](Read-Host 'WorkflowId printed by Prepare (do not start another activation)')).Trim()
    if(-not $identity){{throw 'Prepared WorkflowId required'}}
    $parameters.WorkflowId=$identity
}}
& (Join-Path $PSScriptRoot 'run_bounded_release_workflow.ps1') -Stage $Stage @parameters
"""
    files["Release-MTO-v2.1.26.ps1"] = launcher.replace("\n", "\r\n").encode(
        "utf-8-sig"
    )
    launcher_hash = sha(files["Release-MTO-v2.1.26.ps1"])
    batch = rf"""@echo off
setlocal EnableExtensions
set "MTO_WINDOW_TOOLS=%~dp0"
title MTO v2.1.26 - Prepared Release Window
echo Keep all v2.1.25 release and controlled-acceptance evidence.
echo 1. Prepare - office work continues; download and verify before maintenance
echo 2. Activate prepared workflow - approved financial-entry pause required
echo 3. Verify existing workflow - no new activation
echo 4. Resume entry - after essential READ-ONLY client pilot and strict checks
echo 5. Finalize later - full pilot and manual acceptance after explicit Resume
echo 6. Exit
"%SystemRoot%\System32\choice.exe" /C 123456 /N /M "Choose 1, 2, 3, 4, 5, or 6: "
if errorlevel 6 exit /b 0
if errorlevel 5 goto :finalize
if errorlevel 4 goto :resume
if errorlevel 3 goto :verify
if errorlevel 2 goto :activate
set "MTO_WINDOW_STAGE=Prepare"
goto :run
:activate
set "MTO_WINDOW_STAGE=Activate"
goto :run
:verify
set "MTO_WINDOW_STAGE=Verify"
goto :run
:resume
set "MTO_WINDOW_STAGE=Resume"
goto :run
:finalize
set "MTO_WINDOW_STAGE=Finalize"
:run
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p=Join-Path $env:MTO_WINDOW_TOOLS 'Release-MTO-v2.1.26.ps1'; $s=[Security.Cryptography.SHA256]::Create();$f=$null;try{{$f=[IO.File]::OpenRead($p);$h=[BitConverter]::ToString($s.ComputeHash($f)).Replace('-','')}}finally{{if($f){{$f.Dispose()}};$s.Dispose()}};if($h -cne '{launcher_hash}'){{throw 'Launcher identity mismatch'}};& $p -Stage $env:MTO_WINDOW_STAGE"
set "MTO_WINDOW_RESULT=%ERRORLEVEL%"
echo.
echo Launcher exit code: %MTO_WINDOW_RESULT%
echo Preserve the WorkflowId and evidence. Never rerun activation blindly.
pause
exit /b %MTO_WINDOW_RESULT%
"""
    files["Upgrade-MTO-v2.1.26.cmd"] = batch.replace("\n", "\r\n").encode("ascii")
    output.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        with (output / name).open("xb") as stream:
            stream.write(data)
    archive = output / "MTO_v2.1.26_Deployment_Tools.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as package:
        for name, data in files.items():
            package.writestr(name, data)
    return {
        "status": "BOUNDED_HANDOFF_CREATED_NOT_DEPLOYED",
        "release": "v2.1.26",
        "expected_commit": commit,
        "previous_commit": PREVIOUS,
        "archive": str(archive.resolve()),
        "archive_sha256": sha(archive.read_bytes()),
        "archive_length": archive.stat().st_size,
        "file_sha256": {name: sha(data) for name, data in files.items()},
        "manual_controls_preconfirmed": False,
        "shorter_window_measured_on_office_server": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-validation", type=Path, required=True)
    parser.add_argument("--acceptance-validation", type=Path, required=True)
    parser.add_argument("--risk-acceptance")
    args = parser.parse_args()
    result = create_handoff(
        json.loads(args.manifest.read_text(encoding="utf-8-sig")),
        args.output,
        args.checkpoint_validation,
        args.acceptance_validation,
        risk_acceptance=args.risk_acceptance,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
