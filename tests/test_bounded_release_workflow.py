"""Fail-closed local workflow tests. Never run a production workflow main body."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_bounded_release_workflow.ps1"
POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def invoke(code):
    if not POWERSHELL:
        pytest.skip("PowerShell runtime required")
    preamble = f"""
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile({literal(SCRIPT)},[ref]$tokens,[ref]$errors)
    if($errors.Count){{throw ($errors|Out-String)}}
    foreach($definition in $ast.FindAll({{param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{
        Invoke-Expression $definition.Extent.Text
    }}
    function Assert-NoLinkedPath {{param($Path)}}
    """
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", preamble + code],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_script_parses_and_separates_all_five_stages():
    result = invoke("Write-Output 'PARSE PASS'")
    assert result.returncode == 0, result.stderr
    assert "PARSE PASS" in result.stdout
    source = SCRIPT.read_text(encoding="utf-8")
    assert "'Prepare','Activate','Verify','Resume','Finalize'" in source
    assert "FINANCIAL_ACCOUNT_ROUTING_NO_SCHEMA" in source
    assert "PIP_NO_INDEX='1'" in source
    assert "--dry-run" in source and "--require-hashes" in source
    assert "baseline-before.json" in source and "resume.json" in source
    assert "UNCHANGED_DURING_RELEASE_WINDOW_ONLY" in source
    assert "financial_activity_after_resume_not_attributed=$true" in source
    assert "Assert-AcceptedV225Predecessor" in source
    assert "Remove-Item" not in source
    assert "reset', '--hard" not in source


@pytest.mark.parametrize(
    "answer,success",
    [
        ("ACCEPT v2.1.26", True),
        ("  ACCEPT v2.1.26  ", True),
        ("", False),
        ("ACCEPT v2.1.25", False),
        ("ACCEPT v2.1.26ACCEPT v2.1.26", False),
    ],
)
def test_confirmation_trims_whitespace_but_never_fuzzily_accepts(answer, success):
    result = invoke(f"""
        function Read-Host {{param($Prompt) return {literal(answer)}}}
        Confirm-WindowAction 'approval' 'ACCEPT v2.1.26'
        Write-Output 'CONFIRMED'
    """)
    assert (result.returncode == 0) is success, result.stderr
    assert ("CONFIRMED" in result.stdout) is success


def test_import_pins_bytes_and_imports_definitions_without_executing_main(tmp_path):
    helper = tmp_path / "safe-helper.ps1"
    raw = b"function Test-ReadOnlyDefinition {return 'FUNCTION OK'}\nthrow 'UNSAFE MAIN EXECUTED'\n"
    helper.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest().upper()
    result = invoke(f"""
        Import-PinnedFunctions {literal(helper)} '{digest}' @('Test-ReadOnlyDefinition')
        Test-ReadOnlyDefinition
    """)
    assert result.returncode == 0, result.stderr
    assert "FUNCTION OK" in result.stdout
    assert "UNSAFE MAIN" not in result.stderr


def test_import_rejects_tampered_validation_before_defining_any_function(tmp_path):
    helper = tmp_path / "tampered.ps1"
    helper.write_text("function Injected { 'BAD' }", encoding="utf-8")
    result = invoke(
        f"Import-PinnedFunctions {literal(helper)} '{'0' * 64}' @('Injected');Injected"
    )
    assert result.returncode != 0
    assert "Pinned validation helper changed" in result.stderr
    assert "BAD" not in result.stdout


def test_new_evidence_never_overwrites_an_existing_file(tmp_path):
    destination = tmp_path / "proof.json"
    destination.write_text("preserve", encoding="utf-8")
    result = invoke(f"Write-NewWindowJson {literal(destination)} @{{changed=$true}}")
    assert result.returncode != 0
    assert destination.read_text(encoding="utf-8") == "preserve"


def _identity():
    return {
        "format_version": 2,
        "release_tag": "v2.1.26",
        "expected_commit": "a" * 40,
        "previous_commit": "2e4fabdd10efab6350dea2f77029f08909f61af0",
        "project_root": "C:\\mto",
        "distribution": "C:\\release",
        "manifest_sha256": "manifest",
        "risk_sha256": "risk",
        "internal_only": True,
        "change_profile": "FINANCIAL_ACCOUNT_ROUTING_NO_SCHEMA",
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("format_version", 1),
        ("expected_commit", "b" * 40),
        ("previous_commit", "c" * 40),
        ("manifest_sha256", "changed"),
        ("risk_sha256", "changed"),
        ("internal_only", False),
        ("change_profile", "SCHEMA_CHANGE"),
    ],
)
def test_foreign_or_changed_workflow_identity_is_rejected(field, value):
    state = _identity()
    state[field] = value
    result = invoke(f"""
        $ReleaseTag='v2.1.26';$ExpectedCommit='{'a' * 40}';$PreviousCommit='2e4fabdd10efab6350dea2f77029f08909f61af0'
        $script:ResolvedProject='C:\\mto';$script:ResolvedDistribution='C:\\release'
        $script:ManifestHash='manifest';$script:RiskHash='risk';$InternalOnlyUnsignedRisk=$true
        $state={literal(json.dumps(state))}|ConvertFrom-Json
        Assert-WindowIdentity $state;Write-Output 'WRONG PASS'
    """)
    assert result.returncode != 0
    assert "WRONG PASS" not in result.stdout


@pytest.mark.parametrize(
    "compare,match,success",
    [(True, True, True), (True, False, False), (False, False, True)],
)
def test_strict_comparison_only_inside_release_window(
    tmp_path, compare, match, success
):
    result = invoke(f"""
        $script:RunDirectory={literal(tmp_path)};$script:GateDirectory={literal(tmp_path)}
        $script:WorkflowState=[pscustomobject]@{{baseline_sha256='original-pinned-hash'}}
        function Assert-WindowSnapshot {{param($Path,$Hash) if($Hash -cne 'original-pinned-hash'){{throw 'Wrong original hash'}}}}
        function Invoke-Gate {{param($Name,$Arguments)
            Write-Output ('COMPARE_USED='+[bool]('--compare-to' -cin $Arguments)) | Out-Host
            $report=@{{readiness_issues=@();comparison=@{{financial_invariants_match=${str(match).lower()}}};database=@{{payments=@{{count=999}}}}}}
            [IO.File]::WriteAllText((Join-Path $script:GateDirectory ($Name+'.json')),($report|ConvertTo-Json -Depth 8))
        }}
        [void](Invoke-WindowSnapshot 'snapshot' -CompareActivation:${str(compare).lower()})
        Write-Output 'VERIFIED'
    """)
    assert (result.returncode == 0) is success, result.stderr
    assert f"COMPARE_USED={str(compare)}" in result.stdout
    assert ("VERIFIED" in result.stdout) is success
    assert not (tmp_path / "baseline-before.json").exists()


@pytest.mark.parametrize(
    "path",
    [
        "../activation-proof.json",
        "checks-bad/activation-proof.json",
        "activation-proof.json",
    ],
)
def test_activation_proof_path_is_allowlisted_before_any_read(path, tmp_path):
    result = invoke(f"""
        $script:RunDirectory={literal(tmp_path)}
        $script:WorkflowState=[pscustomobject]@{{activation_proof_path={literal(path)}}}
        function Assert-WindowSnapshot {{param($Path,$Hash) throw 'SHOULD NOT READ'}}
        Assert-ActivationProof
    """)
    assert result.returncode != 0
    assert "Unsafe activation proof path" in result.stderr
    assert "SHOULD NOT READ" not in result.stderr


def test_gate_manifest_cannot_omit_financial_or_manual_readiness_evidence(tmp_path):
    result = invoke(f"""
        function Assert-WindowSnapshot {{param($Path,$Hash)}}
        Assert-WindowGateManifest ([pscustomobject]@{{gate_sha256=[pscustomobject]@{{}}}}) {literal(tmp_path)}
        Write-Output 'WRONG PASS'
    """)
    assert result.returncode != 0
    assert "Required window gate evidence missing" in result.stderr
    assert "WRONG PASS" not in result.stdout


def test_predecessor_keeps_original_blocked_state_and_requires_pinned_completion(
    tmp_path,
):
    result = invoke(f"""
        function Assert-ProtectedEvidenceRoot {{param($Path)}}
        function Assert-WindowEvidenceChild {{param($Path)}}
        function Get-WorkflowSha256 {{param($Path) return '7D253C34FB2AB18E00D642F35457EEFFAEE0A00B66AB5905F579B902E19B0F95'}}
        function Read-Json {{param($Path)
            if($Path.EndsWith('completion.json')){{return [pscustomobject]@{{status='ACCEPTED_WITH_DOCUMENTED_LIMITATIONS'}}}}
            return [pscustomobject]@{{status='BLOCKED';failure_stage='financial-compare';activation_completed=$true;expected_commit='2e4fabdd10efab6350dea2f77029f08909f61af0';completed_utc='';manual_accepted_utc=''}}
        }}
        function Assert-CompletedRecord {{param($Value)
            if($Value.status -cne 'ACCEPTED_WITH_DOCUMENTED_LIMITATIONS'){{throw 'Bad completion'}}
            if($requiredFlags.Count -ne 4){{throw 'Missing original manual flags'}}
            Write-Output 'OLD ACCEPTANCE VALIDATED'
        }}
        Assert-AcceptedV225Predecessor {literal(tmp_path)}
    """)
    assert result.returncode == 0, result.stderr
    assert "OLD ACCEPTANCE VALIDATED" in result.stdout


def test_predecessor_rejects_unknown_completion_before_parsing_private_evidence(
    tmp_path,
):
    result = invoke(f"""
        function Assert-ProtectedEvidenceRoot {{param($Path)}}
        function Assert-WindowEvidenceChild {{param($Path)}}
        function Get-WorkflowSha256 {{param($Path) return ('0'*64)}}
        function Read-Json {{param($Path) throw 'SHOULD NOT PARSE'}}
        Assert-AcceptedV225Predecessor {literal(tmp_path)}
    """)
    assert result.returncode != 0
    assert "Exact accepted v2.1.25 completion evidence required" in result.stderr
    assert "SHOULD NOT PARSE" not in result.stderr


def test_later_acceptance_requires_all_four_genuine_manual_controls():
    result = invoke("""
        $ReleaseTag='v2.1.26';$script:answers=0
        function Read-Host {param($Prompt) $script:answers++;return ' ACCEPT v2.1.26 '}
        $flags=@(Read-BoundedManualAcceptance)
        [pscustomobject]@{Answers=$script:answers;Flags=$flags}|ConvertTo-Json -Compress
    """)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["Answers"] == 4
    assert len(payload["Flags"]) == 4


def test_old_workflow_is_not_edited_or_used_as_an_executable_dot_source():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Assert-CompletedRecord (Read-Json $completion)" in source
    assert ". $legacy" not in source
    assert ". $helper" not in source
    assert "-Mode Finalize" not in source
    assert "$script:MayWriteState -and" in source
    assert (
        "'PIP_NO_INDEX','PIP_FIND_LINKS','PIP_NO_INPUT','PIP_DISABLE_PIP_VERSION_CHECK'"
        in source
    )
    assert (
        "[Environment]::SetEnvironmentVariable($name,$oldPip[$name],'Process')"
        in source
    )
