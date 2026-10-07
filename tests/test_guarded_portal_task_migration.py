import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/install_guarded_portal_task.ps1"


def functions(code):
    ps = shutil.which("powershell.exe")
    if not ps:
        pytest.skip("Windows PowerShell not available")
    path = str(SCRIPT).replace("'", "''")
    command = (
        f"$ErrorActionPreference='Stop';Set-StrictMode -Version Latest;$t=$null;$e=$null;$ast=[Management.Automation.Language.Parser]::ParseFile('{path}',[ref]$t,[ref]$e);if($e.Count){{throw ($e|Out-String)}};foreach($f in $ast.FindAll({{param($n)$n -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{Invoke-Expression $f.Extent.Text}};"
        + code
    )
    return subprocess.run(
        [ps, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        timeout=20,
    )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "other_exe",
        "other_args",
        "user",
        "working_dir",
        "smoke_triggers",
        "daily_times",
    ],
)
def test_only_the_owned_system_publisher_can_migrate(case):
    task = {
        "Actions": [
            {
                "Execute": "PYTHON",
                "Arguments": "APPROVED",
                "WorkingDirectory": r"C:\mto",
            }
        ],
        "Principal": {
            "UserId": "SYSTEM",
            "LogonType": "ServiceAccount",
            "RunLevel": "Highest",
        },
        "Triggers": None,
    }
    daily = case == "daily_times"
    if case == "other_exe":
        task["Actions"][0]["Execute"] = "FOREIGN"
    if case == "other_args":
        task["Actions"][0]["Arguments"] = "FOREIGN"
    if case == "working_dir":
        task["Actions"][0]["WorkingDirectory"] = "FOREIGN"
    if case == "user":
        task["Principal"]["UserId"] = "FOREIGN"
    if case == "smoke_triggers":
        task["Triggers"] = [{"Enabled": True}]
    if daily:
        task["Triggers"] = [
            {"DaysInterval": 1, "Enabled": True, "StartBoundary": f"2026-10-07T{t}:00"}
            for t in ["00:15", "06:15", "12:15", "18:16"]
        ]
    literal = json.dumps(task).replace("'", "''")
    result = functions(
        f"$x='{literal}'|ConvertFrom-Json;Assert-TaskIdentity $x 'PYTHON' 'APPROVED' ${str(daily).lower()}"
    )
    assert (result.returncode == 0) == (case == "valid"), result.stderr


def test_action_change_requires_current_system_receipt_before_and_after():
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.index("Start-ScheduledTask -TaskName $smokeName") < text.index(
        "Set-ScheduledTask -TaskName $name"
    )
    assert text.count("Assert-Receipt (Get-Content") == 2
    action = next(
        line
        for line in text.splitlines()
        if line.strip().startswith("Set-ScheduledTask")
    )
    assert (
        "-Trigger" not in action
        and "-Principal" not in action
        and "-Settings" not in action
    )
    assert "APPROVE APP PORTAL BRIDGE v2.1.17" in text
    assert "Stop-ScheduledTask" not in text and "Remove-Item" not in text
    assert "Unregister-ScheduledTask -TaskName $smokeName" in text


def test_workflow_uses_repaired_native_capture_and_migrates_before_postchecks():
    text = (SCRIPT.parent / "run_release_workflow.ps1").read_text(encoding="utf-8")
    assert "Invoke-CapturedNative $script:Python" in text
    assert "& $script:Python @Arguments *> $log" not in text
    assert text.index("scripts\\install_guarded_portal_task.ps1") < text.index(
        "Invoke-Gate 'production-preflight'"
    )
