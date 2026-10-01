"""Release orchestration contracts and isolated PowerShell function tests.

Never invoke the full workflow here: all production commands are mocked or
tested as fail-closed functions extracted through the PowerShell parser.
"""

import json
import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_release_workflow.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def invoke_functions(code):
    if not POWERSHELL:
        pytest.skip("PowerShell function tests require a PowerShell runtime")
    preamble = f"""
    $ErrorActionPreference='Stop'
    $tokens=$null; $errors=$null
    $ast=[System.Management.Automation.Language.Parser]::ParseFile({ps_literal(SCRIPT)},[ref]$tokens,[ref]$errors)
    if($errors.Count){{throw ($errors | Out-String)}}
    foreach($definition in $ast.FindAll({{param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst]}},$false)){{
        Invoke-Expression $definition.Extent.Text
    }}
    """
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", preamble + code],
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_workflow_retains_existing_updater_and_every_required_gate():
    source = SCRIPT.read_text(encoding="utf-8")
    for token in (
        "scripts\\apply_immutable_release.ps1",
        "scripts.phase4_reliability_preflight",
        "scripts.phase5_audit_observability_preflight",
        "--require-live-event",
        "scripts.phase6_financial_reconciliation_preflight",
        "scripts.capture_remediation_baseline",
        "--compare-to",
        "scripts.phase9_production_readiness_certification",
        "scripts.check_api_readiness",
        "'pip', 'check'",
        "Invoke-OperationsSmoke",
        "Read-ManualAcceptance",
        "Read-Host",
        "READY_FOR_MANUAL_ACCEPTANCE",
        "baseline_sha256",
        "FileShare]::None",
    ):
        assert token in source
    assert "git reset" not in source.lower()
    assert "reset', '--hard" not in source
    assert "Remove-Item" not in source
    assert (
        "APPLY UNSIGNED INTERNAL-ONLY" not in source
    )  # approval belongs to the existing updater


def test_preparation_is_before_activation_and_finalize_is_separate():
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.index("Invoke-Gate 'backup'") < source.index(
        "Invoke-Gate 'baseline-before'"
    )
    assert source.index("Invoke-Gate 'baseline-before'") < source.index(
        "'System32\\WindowsPowerShell\\v1.0\\powershell.exe') $updaterArguments"
    )
    assert source.index("if ($Stage -eq 'Finalize')") < source.index(
        "@(Read-ManualAcceptance $ReleaseTag)"
    )
    assert (
        "No evidence will be overwritten" in source
        or "no evidence will be overwritten" in source
    )
    assert "'checks-'" in source
    assert "activation_completed = $false" in source
    assert "$script:WorkflowState.activation_completed = $true" in source


def test_script_parses_in_windows_powershell():
    result = invoke_functions("Write-Output 'PARSE PASS'")
    assert result.returncode == 0, result.stderr
    assert "PARSE PASS" in result.stdout


def test_workflow_sha256_matches_python_without_cmdlet_autoload(tmp_path):
    sample = tmp_path / "hash sample.bin"
    sample.write_bytes(b"Known SHA256 test material, not a production secret.")
    result = invoke_functions(f"Get-WorkflowSha256 {ps_literal(sample)}")
    assert result.returncode == 0, result.stderr
    assert (
        result.stdout.strip() == hashlib.sha256(sample.read_bytes()).hexdigest().upper()
    )


def test_native_nonzero_exit_is_not_ignored():
    result = invoke_functions(
        f"Invoke-CheckedNative {ps_literal(POWERSHELL)} @('-NoProfile','-Command','exit 9'); Write-Output 'WRONG PASS'"
    )
    assert result.returncode != 0
    assert "WRONG PASS" not in result.stdout


@pytest.mark.parametrize("final", [False, True])
def test_certification_arguments_do_not_auto_attest_manual_checks(final):
    result = invoke_functions(f"""
        $script:ResolvedDistribution='C:\\approved-package'; $script:ResolvedRisk='C:\\approved-risk.json'
        $InternalOnlyUnsignedRisk=$true
        @(Get-CertificationArguments ${str(final).lower()} 'test-output.json') | ConvertTo-Json -Compress
    """)
    assert result.returncode == 0, result.stderr
    arguments = json.loads(result.stdout)
    assert ("--final" if final else "--preflight") in arguments
    assert "internal-municipal" in arguments
    assert not any(argument.startswith("--confirm-") for argument in arguments)


def test_manual_acceptance_requires_each_of_four_explicit_answers():
    result = invoke_functions("""
        $script:answers=0
        function Read-Host {param($Prompt) $script:answers++; return 'ACCEPT v2.1.99'}
        $flags=@(Read-ManualAcceptance 'v2.1.99')
        [pscustomobject]@{Answers=$script:answers; Flags=$flags} | ConvertTo-Json -Compress
    """)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Answers"] == 4
    assert len(payload["Flags"]) == 4
    assert "--confirm-isolated-restore-drill" in payload["Flags"]


def test_manual_acceptance_stops_on_missing_answer():
    result = invoke_functions("""
        function Read-Host {param($Prompt) return ''}
        Read-ManualAcceptance 'v2.1.99'; Write-Output 'WRONG PASS'
    """)
    assert result.returncode != 0
    assert "WRONG PASS" not in result.stdout


@pytest.mark.parametrize(
    "field,value",
    [
        ("activation_completed", False),
        ("expected_commit", "0" * 40),
        ("manifest_sha256", "changed"),
        ("risk_sha256", "changed"),
        ("internal_only", False),
        ("distribution", "C:\\wrong-package"),
    ],
)
def test_resume_rejects_changed_identity_or_incomplete_activation(field, value):
    state = {
        "format_version": 1,
        "release_tag": "v2.1.99",
        "expected_commit": "a" * 40,
        "previous_commit": "b" * 40,
        "project_root": "C:\\mto",
        "distribution": "C:\\package",
        "internal_only": True,
        "risk_sha256": "risk",
        "manifest_sha256": "manifest",
        "activation_completed": True,
    }
    state[field] = value
    result = invoke_functions(f"""
        $state={ps_literal(json.dumps(state))} | ConvertFrom-Json
        Assert-ResumeState $state 'v2.1.99' '{'a' * 40}' '{'b' * 40}' 'C:\\mto' 'C:\\package' $true 'risk' 'manifest'
        Write-Output 'WRONG PASS'
    """)
    assert result.returncode != 0
    assert "WRONG PASS" not in result.stdout


def test_operations_failure_stops_remaining_postchecks(tmp_path):
    result = invoke_functions(f"""
        $script:ResolvedProject='C:\\mto'; $script:ResolvedDistribution='C:\\package'; $script:Python='C:\\mto\\venv\\Scripts\\python.exe'
        $script:RunDirectory={ps_literal(tmp_path)}; $script:WorkflowState=[ordered]@{{current_step=''; last_check_directory=''}}; $script:StatePath='unused'
        $ExpectedCommit='{'a' * 40}'; $ReleaseTag='v2.1.99'
        function Assert-Checkout {{param($Root,$Commit)}}
        function Assert-ReleaseIdentity {{param($Tag,$Commit,$Package)}}
        function Write-WorkflowState {{param($State,$Path)}}
        function Invoke-Gate {{param($Name,$Arguments) Write-Output ('GATE:'+ $Name)}}
        function Invoke-OperationsSmoke {{param($Root,$PythonPath) throw 'mock operations failure'}}
        Invoke-PostChecks
    """)
    assert result.returncode != 0
    assert "GATE:api-readiness" in result.stdout
    assert "GATE:production-preflight" not in result.stdout
    assert "GATE:financial-compare" not in result.stdout


def test_gate_failure_is_retained_and_not_marked_pass(tmp_path):
    result = invoke_functions(f"""
        $script:Python={ps_literal(POWERSHELL)}; $script:GateDirectory={ps_literal(tmp_path)}
        $script:WorkflowState=[ordered]@{{current_step=''}}; $script:StatePath='unused'
        function Write-WorkflowState {{param($State,$Path)}}
        Invoke-Gate 'failed-test' @('-NoProfile','-Command','Write-Output evidence; exit 2')
    """)
    assert result.returncode != 0
    assert "failed-test: PASS" not in result.stdout
    assert "evidence" in (tmp_path / "failed-test.log").read_text(encoding="utf-16")


@pytest.mark.parametrize(
    "task_result,health,age,future,expected",
    [
        (0, "PASS", 0, 0, True),
        (2, "PASS", 0, 0, False),
        (0, "FAIL", 0, 0, False),
        (0, "PASS", 300, 0, False),
        (0, "PASS", 0, 300, False),
    ],
)
def test_operations_requires_successful_new_run_and_fresh_passing_report(
    task_result, health, age, future, expected
):
    result = invoke_functions(f"""
        $script:taskStarted=$false
        function Get-ScheduledTask {{param($TaskName,$ErrorAction)
            return [pscustomobject]@{{State='Ready'; Actions=@([pscustomobject]@{{
                Execute='C:\\mto\\venv\\Scripts\\python.exe'; Arguments='-m scripts.run_operations_health_check --retention-days 400'; WorkingDirectory='C:\\mto'
            }})}}
        }}
        function Get-ScheduledTaskInfo {{param($TaskName)
            $last=if($script:taskStarted){{[datetime]::Now}}else{{[datetime]::Now.AddMinutes(-5)}}
            return [pscustomobject]@{{LastRunTime=$last; LastTaskResult={task_result}}}
        }}
        function Start-ScheduledTask {{param($TaskName) $script:taskStarted=$true}}
        function Start-Sleep {{param($Seconds)}}
        function Get-ChildItem {{param($LiteralPath,$Filter,[switch]$File)
            return [pscustomobject]@{{FullName='synthetic-report.json'; LastWriteTimeUtc=[datetime]::UtcNow.AddSeconds(1-{age})}}
        }}
        function Get-Content {{param($LiteralPath,[switch]$Raw)
            return (@{{report_type='MTO_OPERATIONS_HEALTH'; status='{health}'; timestamp_utc=[datetime]::UtcNow.AddSeconds(1-{age}+{future}).ToString('o')}} | ConvertTo-Json)
        }}
        Invoke-OperationsSmoke 'C:\\mto' 'C:\\mto\\venv\\Scripts\\python.exe'
    """)
    assert (result.returncode == 0) is expected, result.stderr
    assert ("operations-smoke: PASS" in result.stdout) is expected
