"""Generate a release-pinned, offline deployment launcher (not a deployment).

The tools ZIP is separate from the immutable six-file application package.
Its independently supplied SHA256 must be checked before the launcher is run.
No credentials or private certificate material are read or included.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

WORKFLOW = Path(__file__).with_name("run_release_workflow.ps1")
RELEASE_PATTERN = re.compile(r"v\d+\.\d+\.\d+\Z")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


def ps_literal(value: str) -> str:
    if any(character in value for character in ("\r", "\n", "\x00")):
        raise ValueError("Launcher values cannot contain control characters.")
    return "'" + value.replace("'", "''") + "'"


def create_handoff(
    manifest: dict,
    previous_commit: str,
    output: Path,
    *,
    project_root: str = r"C:\mto",
    distribution: str | None = None,
    risk_acceptance: str | None = None,
) -> dict:
    tag = str(manifest.get("version") or "")
    commit = str(manifest.get("source_commit") or "")
    if not RELEASE_PATTERN.fullmatch(tag) or not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError(
            "Manifest must identify an immutable release tag and full source commit."
        )
    if not COMMIT_PATTERN.fullmatch(previous_commit) or previous_commit == commit:
        raise ValueError("A different full previous production commit is required.")
    if (
        manifest.get("product_version") != tag[1:]
        or manifest.get("material_hash_mode") != "git-blob-sha256"
    ):
        raise ValueError("Manifest product version or material hash mode is invalid.")
    package = distribution or rf"C:\ProgramData\MTO\releases\{tag}"
    parameters = {
        "ReleaseTag": tag,
        "ExpectedCommit": commit,
        "PreviousCommit": previous_commit,
        "ProjectRoot": project_root,
        "Distribution": package,
    }
    assignments = "\n".join(
        f"    {key} = {ps_literal(value)}" for key, value in parameters.items()
    )
    if risk_acceptance:
        assignments += (
            "\n    InternalOnlyUnsignedRisk = $true\n    RiskAcceptance = "
            + ps_literal(risk_acceptance)
        )
    workflow_bytes = WORKFLOW.read_bytes()
    workflow_hash = hashlib.sha256(workflow_bytes).hexdigest().upper()
    launcher = f"""# Approved release launcher. Verify the tools archive before executing.
param([ValidateSet('Activate','Verify','Finalize')][string]$Stage='Activate')
$ErrorActionPreference='Stop'
$tool=Join-Path $PSScriptRoot 'run_release_workflow.ps1'
$sha=[Security.Cryptography.SHA256]::Create(); $stream=$null
try{{ $stream=[IO.File]::OpenRead($tool); $actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','') }}
finally{{ if($stream){{$stream.Dispose()}}; $sha.Dispose() }}
if($actual -ne '{workflow_hash}'){{throw 'Workflow helper identity mismatch'}}
$parameters=@{{
{assignments}
}}
if($Stage -ne 'Activate'){{
    $workflowId=Read-Host 'Enter the WorkflowId printed by Deploy (do not start another activation)'
    if([string]::IsNullOrWhiteSpace($workflowId)){{throw 'WorkflowId is required'}}
    $parameters.WorkflowId=$workflowId
}}
& $tool -Stage $Stage @parameters
"""
    launcher_bytes = launcher.replace("\n", "\r\n").encode("utf-8-sig")
    launcher_hash = hashlib.sha256(launcher_bytes).hexdigest().upper()
    launcher_name = f"Release-MTO-{tag}.ps1"
    # Keep all paths relative to this verified tools folder; never construct a
    # command from untrusted package paths in cmd.exe.
    batch = rf"""@echo off
setlocal EnableExtensions
title MTO {tag} Controlled Release
echo Run this launcher as Administrator. Close client apps before Deploy.
echo 1. Deploy (backup, existing updater, and automated checks)
echo 2. Recheck (no activation)
echo 3. Finalize (after the client pilot and evidence review)
echo 4. Exit
"%SystemRoot%\System32\choice.exe" /C 1234 /N /M "Choose 1, 2, 3, or 4: "
if errorlevel 4 exit /b 0
if errorlevel 3 goto :finalize
if errorlevel 2 goto :verify
set "MTO_WORKFLOW_STAGE=Activate"
goto :run
:verify
set "MTO_WORKFLOW_STAGE=Verify"
goto :run
:finalize
set "MTO_WORKFLOW_STAGE=Finalize"
:run
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $p=Join-Path $env:MTO_WORKFLOW_TOOLS '{launcher_name}'; $sha=[Security.Cryptography.SHA256]::Create(); $stream=$null; try{{$stream=[IO.File]::OpenRead($p); $actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','')}}finally{{if($stream){{$stream.Dispose()}}; $sha.Dispose()}}; if($actual -ne '{launcher_hash}'){{throw 'Release launcher identity mismatch'}}; & $p -Stage $env:MTO_WORKFLOW_STAGE"
set "MTO_WORKFLOW_RESULT=%ERRORLEVEL%"
echo.
echo Launcher exit code: %MTO_WORKFLOW_RESULT%
echo Keep the WorkflowId and evidence. A nonzero result is not a PASS.
pause
exit /b %MTO_WORKFLOW_RESULT%
"""
    # %~dp0 is carried through an environment value, not interpolated inside
    # PowerShell source; this safely handles spaces and apostrophes in paths.
    batch = batch.replace("title MTO", 'set "MTO_WORKFLOW_TOOLS=%~dp0"\ntitle MTO', 1)
    batch_bytes = batch.replace("\n", "\r\n").encode("ascii")
    files = {
        "run_release_workflow.ps1": workflow_bytes,
        launcher_name: launcher_bytes,
        f"Upgrade-MTO-{tag}.cmd": batch_bytes,
    }
    # Refuse an existing handoff directory; do not overwrite a published kit.
    output.mkdir(parents=True, exist_ok=False)
    for name, content in files.items():
        (output / name).write_bytes(content)
    archive = output / f"MTO_{tag}_Deployment_Tools.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package_zip:
        for name in files:
            package_zip.write(output / name, arcname=name)
    return {
        "release": tag,
        "expected_commit": commit,
        "previous_commit": previous_commit,
        "archive": str(archive.resolve()),
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest().upper(),
        "archive_length": archive.stat().st_size,
        "file_sha256": {
            name: hashlib.sha256(content).hexdigest().upper()
            for name, content in files.items()
        },
        "status": "HANDOFF_CREATED_NOT_DEPLOYED",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--previous-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--project-root", default=r"C:\mto")
    parser.add_argument("--distribution")
    parser.add_argument("--risk-acceptance")
    args = parser.parse_args(argv)
    result = create_handoff(
        json.loads(args.manifest.read_text(encoding="utf-8-sig")),
        args.previous_commit,
        args.output,
        project_root=args.project_root,
        distribution=args.distribution,
        risk_acceptance=args.risk_acceptance,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
