"""Complete control-flow rehearsal with synthetic files and mocked server work.

No workflow main body, Windows service, real Git operation, backup, cloud access
or application database is invoked. The stage branch itself is extracted from
the production script, not reimplemented as a second state machine.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_bounded_release_workflow.ps1"
# Rehearse the exact Windows PowerShell runtime used by the server launcher.
# The native stage branch contains Windows file-URI and SystemRoot semantics;
# Linux CI still runs the platform-independent policy/function/kit tests.
POWERSHELL = shutil.which("powershell.exe")


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def rehearse(tmp_path, tail):
    if not POWERSHELL:
        pytest.skip("Windows PowerShell required for the native stage rehearsal")
    code = f"""
    $ErrorActionPreference='Stop';Set-StrictMode -Version Latest
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile({literal(SCRIPT)},[ref]$tokens,[ref]$errors)
    if($errors.Count){{throw ($errors|Out-String)}}
    foreach($definition in $ast.FindAll({{param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst]}},$false)){{Invoke-Expression $definition.Extent.Text}}
    $source=[IO.File]::ReadAllText({literal(SCRIPT)})
    $start=$source.IndexOf("    if(`$Stage -ceq 'Prepare'){{")
    $end=$source.IndexOf("    Write-Host ('MTO BOUNDED RELEASE:",$start)
    if($start -lt 0 -or $end -le $start){{throw 'Stage extraction failed'}}
    $stageBody=[scriptblock]::Create($source.Substring($start,$end-$start))
    $ReleaseTag='v2.1.26';$ExpectedCommit='{'a' * 40}';$PreviousCommit='2e4fabdd10efab6350dea2f77029f08909f61af0'
    $WorkflowId='v2.1.26-20261105T000000Z-abcdef01';$InternalOnlyUnsignedRisk=$true
    $resolvedEvidence={literal(tmp_path)}
    $script:RunDirectory=Join-Path $resolvedEvidence $WorkflowId
    $script:ResolvedProject=Join-Path $resolvedEvidence 'synthetic-project'
    $script:ResolvedDistribution=Join-Path $resolvedEvidence 'synthetic-distribution'
    $script:StatePath=Join-Path $script:RunDirectory 'workflow-state.json'
    $script:Python='NOT-A-REAL-PYTHON';$script:ResolvedRisk='NOT-A-REAL-RISK'
    $script:ManifestHash='manifest';$script:RiskHash='risk';$script:WorkflowState=$null
    $script:simulatedHead=$PreviousCommit;$script:businessChanged=$false;$script:failBridgeOnce=$false
    $script:commands=New-Object 'Collections.Generic.List[string]'
    function Assert-NoLinkedPath {{param($Path)}}
    function Assert-ProtectedEvidenceRoot {{param($Path)}}
    function Assert-AcceptedV225Predecessor {{param($Root) $script:commands.Add('PREDECESSOR-VERIFIED')}}
    function Assert-ReleaseIdentity {{param($Tag,$Commit,$Package)}}
    function Assert-Checkout {{param($Root,$RequiredCommit)
        if($script:simulatedHead -cne $RequiredCommit){{throw 'Simulated source mismatch'}}
    }}
    function Get-CheckedGit {{param($Arguments)
        if($Arguments[0] -ceq 'rev-parse'){{return 'same-runtime-material'}}
        if($Arguments[0] -ceq 'diff'){{return ''}}
        throw 'Unmocked Git request'
    }}
    function Get-WorkflowSha256 {{param($Path)
        $s=[Security.Cryptography.SHA256]::Create();$f=[IO.File]::OpenRead($Path)
        try{{return [BitConverter]::ToString($s.ComputeHash($f)).Replace('-','')}}finally{{$f.Dispose();$s.Dispose()}}
    }}
    function Write-WorkflowState {{param($State,$Path)
        [IO.File]::WriteAllText($Path,($State|ConvertTo-Json -Depth 20))
    }}
    function Read-Host {{param($Prompt)
        if($Prompt.Contains('CONFIRM ESSENTIAL')){{return '  CONFIRM ESSENTIAL CLIENT PILOT v2.1.26  '}}
        if($Prompt.Contains('BEGIN MTO')){{return '  BEGIN MTO RELEASE v2.1.26  '}}
        return '  ACCEPT v2.1.26  '
    }}
    function Invoke-CapturedNative {{param($Executable,$Arguments,$Log)
        if($Executable -cne 'git' -or $Arguments[0] -cne 'show'){{throw 'Unmocked capture'}}
        [IO.File]::WriteAllText(($Log+'.stdout.log'),'synthetic==1.0.0')
        return 0
    }}
    function Invoke-CheckedNative {{param($Executable,$Arguments)
        if($Executable -ceq 'icacls.exe'){{return}}
        if(@($Arguments|Where-Object {{$_ -like '*apply_immutable_release.ps1'}}).Count){{
            if($env:PIP_NO_INDEX -cne '1' -or -not $env:PIP_FIND_LINKS){{throw 'Online install inside pause'}}
            $script:commands.Add('IMMUTABLE-UPDATER');$script:simulatedHead=$ExpectedCommit;return
        }}
        if(@($Arguments|Where-Object {{$_ -like '*install_guarded_portal_task.ps1'}}).Count){{
            if($script:failBridgeOnce){{$script:failBridgeOnce=$false;throw 'SIMULATED BRIDGE FAILURE'}}
            $script:commands.Add('PUBLISHER-VERIFIED');return
        }}
        throw 'Unexpected native request'
    }}
    function Enter-PortalPublisherMaintenanceLock {{
        $value=[pscustomobject]@{{}}
        $value|Add-Member ScriptMethod Unlock {{param($Offset,$Length)}}
        $value|Add-Member ScriptMethod Dispose {{}}
        return $value
    }}
    function Get-CertificationArguments {{param($Final,$Output)
        return @('--synthetic-mode',([string]$Final),'--output',$Output)
    }}
    function Invoke-AuditGate {{param($Name) Invoke-Gate $Name @('--output',(Join-Path $script:GateDirectory ($Name+'.json')))}}
    function Invoke-OperationsSmoke {{param($Root,$PythonPath)
        $folder=Join-Path $Root 'logs/operations';[IO.Directory]::CreateDirectory($folder)|Out-Null
        [IO.File]::WriteAllText((Join-Path $folder 'operations-health-synthetic.json'),'{{"status":"PASS"}}')
    }}
    function Invoke-Gate {{param($Name,$Arguments)
        $script:WorkflowState.current_step=$Name
        Write-WorkflowState $script:WorkflowState $script:StatePath
        $script:commands.Add($Stage+':'+$Name+':'+[string]('--compare-to' -cin $Arguments))
        [IO.File]::WriteAllText((Join-Path $script:GateDirectory ($Name+'.log')),'synthetic successful gate')
        if($Name -ceq 'dependency-download'){{
            $destination=$Arguments[[array]::IndexOf($Arguments,'--dest')+1]
            [IO.File]::WriteAllText((Join-Path $destination 'synthetic.whl'),'SYNTHETIC WHEEL')
        }}
        $index=[array]::IndexOf($Arguments,'--output')
        if($index -lt 0){{return}}
        $output=$Arguments[$index+1]
        $status=if($Name -ceq 'production-preflight'){{'READY_FOR_MANUAL_ACCEPTANCE'}}elseif($Name -ceq 'production-final'){{'PASS_WITH_ACCEPTED_RISK'}}else{{'PASS'}}
        $payload=@{{status=$status;readiness_issues=@();comparison=@{{financial_invariants_match=(-not $script:businessChanged)}};database=@{{payments=@{{count=$(if($script:businessChanged){{101}}else{{100}})}}}}}}
        [IO.File]::WriteAllText($output,($payload|ConvertTo-Json -Depth 10))
    }}
    function Run-Stage {{param([string]$SelectedStage)
        $Stage=$SelectedStage
        & $stageBody
    }}
    {tail}
    """
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        text=True,
        timeout=40,
    )


def test_complete_rehearsal_accepts_later_business_without_replacing_baseline(tmp_path):
    result = rehearse(
        tmp_path,
        """
        Run-Stage 'Prepare'
        if($script:commands -match 'IMMUTABLE-UPDATER|Prepare:backup'){throw 'Prepare mutated production'}
        Run-Stage 'Activate'
        if($script:WorkflowState.status -cne 'READY_FOR_ESSENTIAL_PILOT'){throw 'Missing pilot boundary'}
        if($script:WorkflowState.resume_utc){throw 'Activation silently resumed entry'}
        $original=Get-WorkflowSha256 (Join-Path $script:RunDirectory 'baseline-before.json')
        Run-Stage 'Resume'
        if($script:WorkflowState.status -cne 'ENTRY_RESUMED_PENDING_ACCEPTANCE'){throw 'Explicit resume missing'}
        $script:businessChanged=$true
        Run-Stage 'Finalize'
        if($script:WorkflowState.status -cne 'PASS_WITH_ACCEPTED_RISK'){throw 'Late acceptance blocked on legitimate new activity'}
        if(@($script:commands|Where-Object {$_ -like 'Finalize:*:True'}).Count){throw 'Finalize compared across resumed office activity'}
        if((Get-WorkflowSha256 (Join-Path $script:RunDirectory 'baseline-before.json')) -cne $original){throw 'Original baseline overwritten'}
        $completion=Get-Content -LiteralPath (Join-Path $script:RunDirectory 'completion.json') -Raw|ConvertFrom-Json
        if($completion.comparison_scope -cne 'UNCHANGED_DURING_RELEASE_WINDOW_ONLY'){throw 'False unchanged-data claim'}
        Run-Stage 'Verify'
        if($script:WorkflowState.status -cne 'PASS_WITH_ACCEPTED_RISK'){throw 'Verify downgraded completed acceptance'}
        if(@($script:commands|Where-Object {$_ -ceq 'IMMUTABLE-UPDATER'}).Count -ne 1){throw 'Repeated activation'}
        Write-Output 'REHEARSAL PASS'
    """,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "REHEARSAL PASS" in result.stdout


def test_drift_inside_window_never_authorizes_resume(tmp_path):
    result = rehearse(
        tmp_path,
        """
        Run-Stage 'Prepare';Run-Stage 'Activate'
        $script:businessChanged=$true
        try{Run-Stage 'Resume';throw 'WRONG RESUME'}catch{
            if($_.Exception.Message -ceq 'WRONG RESUME'){throw}
        }
        if(Test-Path -LiteralPath (Join-Path $script:RunDirectory 'resume.json')){throw 'Unsafe resume record exists'}
        if($script:WorkflowState.resume_utc){throw 'Unsafe resume timestamp exists'}
        Write-Output 'DRIFT BLOCKED'
    """,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "DRIFT BLOCKED" in result.stdout


def test_admin_acceptance_cannot_bypass_resume_or_repeat_completion(tmp_path):
    result = rehearse(
        tmp_path,
        """
        Run-Stage 'Prepare';Run-Stage 'Activate'
        try{Run-Stage 'Finalize';throw 'WRONG EARLY ACCEPTANCE'}catch{
            if($_.Exception.Message -ceq 'WRONG EARLY ACCEPTANCE'){throw}
        }
        if(Test-Path -LiteralPath (Join-Path $script:RunDirectory 'completion.json')){throw 'Premature completion exists'}
        Run-Stage 'Resume';Run-Stage 'Finalize'
        $original=Get-WorkflowSha256 (Join-Path $script:RunDirectory 'completion.json')
        try{Run-Stage 'Finalize';throw 'WRONG REPEATED ACCEPTANCE'}catch{
            if($_.Exception.Message -ceq 'WRONG REPEATED ACCEPTANCE'){throw}
        }
        if((Get-WorkflowSha256 (Join-Path $script:RunDirectory 'completion.json')) -cne $original){throw 'Original completion overwritten'}
        Write-Output 'ACCEPTANCE BOUNDARIES PASS'
    """,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "ACCEPTANCE BOUNDARIES PASS" in result.stdout


def test_failed_bridge_rechecks_without_a_second_source_activation(tmp_path):
    result = rehearse(
        tmp_path,
        """
        Run-Stage 'Prepare';$script:failBridgeOnce=$true
        try{Run-Stage 'Activate';throw 'WRONG BRIDGE PASS'}catch{
            if($_.Exception.Message -ceq 'WRONG BRIDGE PASS'){throw}
        }
        if(-not $script:WorkflowState.activation_completed){throw 'Successful updater was forgotten'}
        if($script:WorkflowState.activation_proof_sha256){throw 'Failed postchecks were certified'}
        Run-Stage 'Verify'
        if($script:WorkflowState.status -cne 'READY_FOR_ESSENTIAL_PILOT'){throw 'Post-activation recheck failed'}
        if(@($script:commands|Where-Object {$_ -ceq 'IMMUTABLE-UPDATER'}).Count -ne 1){throw 'Repeated updater'}
        if($script:WorkflowState.resume_utc){throw 'Recheck silently resumed entry'}
        Write-Output 'RECHECK WITHOUT REACTIVATION PASS'
    """,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "RECHECK WITHOUT REACTIVATION PASS" in result.stdout


def test_changed_baseline_cannot_be_replaced_to_authorize_resume(tmp_path):
    result = rehearse(
        tmp_path,
        """
        Run-Stage 'Prepare';Run-Stage 'Activate'
        [IO.File]::WriteAllText((Join-Path $script:RunDirectory 'baseline-before.json'),'ALTERED SYNTHETIC EVIDENCE')
        try{Run-Stage 'Resume';throw 'WRONG TAMPER PASS'}catch{
            if($_.Exception.Message -ceq 'WRONG TAMPER PASS'){throw}
        }
        if(Test-Path -LiteralPath (Join-Path $script:RunDirectory 'resume.json')){throw 'Tampered evidence authorized entry'}
        Write-Output 'BASELINE TAMPER BLOCKED'
    """,
    )
    assert result.returncode == 0, result.stderr + result.stdout
    assert "BASELINE TAMPER BLOCKED" in result.stdout
