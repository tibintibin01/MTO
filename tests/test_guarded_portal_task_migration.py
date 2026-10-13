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
        if "Set-ScheduledTask -TaskName $name" in line
    )
    assert (
        "-Trigger" not in action
        and "-Principal" not in action
        and "-Settings" not in action
    )
    assert "APPROVE APP PORTAL BRIDGE $ReleaseTag" in text
    assert "Stop-ScheduledTask" not in text and "Remove-Item" not in text
    assert "Unregister-ScheduledTask -TaskName $smokeName" in text


def test_workflow_uses_repaired_native_capture_and_migrates_before_postchecks():
    text = (SCRIPT.parent / "run_release_workflow.ps1").read_text(encoding="utf-8")
    assert "Invoke-CapturedNative $script:Python" in text
    assert "& $script:Python @Arguments *> $log" not in text
    assert text.index("scripts\\install_guarded_portal_task.ps1") < text.index(
        "Invoke-Gate 'production-preflight'"
    )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "commit",
        "version",
        "revision",
        "owner",
        "status",
        "prior_commit",
        "empty",
    ],
)
def test_reports_release_requires_the_verified_previous_bridge(case):
    before = "a" * 40
    state = {
        "approved_source_commit": before,
        "approved_product_version": "2.1.17",
        "approved_bridge_revision": "app-guarded-publish-v1",
    }
    intent = {
        "owner": "MTO_PORTAL_PUBLICATION_20261007",
        "status": "VERIFIED",
        "expected_commit": before,
    }
    if case == "commit":
        state["approved_source_commit"] = "b" * 40
    if case == "version":
        state["approved_product_version"] = "2.1.16"
    if case == "revision":
        state["approved_bridge_revision"] = "FOREIGN"
    if case == "owner":
        intent["owner"] = "FOREIGN"
    if case == "status":
        intent["status"] = "IN_PROGRESS"
    if case == "prior_commit":
        intent["expected_commit"] = "b" * 40
    if case == "empty":
        before = ""
    state_json, intent_json = json.dumps(state), json.dumps(intent)
    result = functions(
        f"$s='{state_json}'|ConvertFrom-Json;$i='{intent_json}'|ConvertFrom-Json;Assert-PreviousBridgeApproval $s $i '{before}'"
    )
    assert (result.returncode == 0) == (case == "valid"), result.stderr


@pytest.mark.parametrize("case", ["valid", "tag", "before", "commit", "status"])
def test_resume_intent_is_bound_to_the_exact_reports_transition(case):
    intent = {
        "owner": "OWNER",
        "expected_commit": "b" * 40,
        "previous_commit": "a" * 40,
        "release_tag": "v2.1.18",
        "status": "IN_PROGRESS",
    }
    if case == "tag":
        intent["release_tag"] = "v2.1.19"
    if case == "before":
        intent["previous_commit"] = "c" * 40
    if case == "commit":
        intent["expected_commit"] = "c" * 40
    if case == "status":
        intent["status"] = "FOREIGN"
    literal = json.dumps(intent)
    result = functions(
        f"$i='{literal}'|ConvertFrom-Json;Assert-MigrationIntent $i 'OWNER' '{'b'*40}' 'v2.1.18' '{'a'*40}'"
    )
    assert (result.returncode == 0) == (case == "valid"), result.stderr


def test_reports_reapproval_preserves_old_intent_and_does_not_rewrite_unchanged_action():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "'app-bridge-migration-'+$ReleaseTag+'.json'" in text
    assert "Assert-PreviousBridgeApproval $state $priorIntent $PreviousCommit" in text
    assert "Previous app bridge schedule marker mismatch" in text
    assert "Interrupted reapproval state is inconsistent" in text
    assert "if(@($task.Actions)[0].Execute -cne $newExecute" in text
    assert "-Trigger" not in next(
        line
        for line in text.splitlines()
        if "Set-ScheduledTask -TaskName $name" in line
    )


def test_reports_workflow_reapproves_before_checks_and_serializes_source_activation():
    text = (SCRIPT.parent / "run_release_workflow.ps1").read_text(encoding="utf-8")
    assert "@('v2.1.17','v2.1.18')" in text
    assert "'-ReleaseTag',$ReleaseTag,'-PreviousCommit',$PreviousCommit" in text
    assert text.index(
        "$portalActivationLock=Enter-PortalPublisherMaintenanceLock"
    ) < text.index(
        "'System32\\WindowsPowerShell\\v1.0\\powershell.exe') $updaterArguments"
    )
    assert "$portalActivationLock.Unlock(0,1);$portalActivationLock.Dispose()" in text
