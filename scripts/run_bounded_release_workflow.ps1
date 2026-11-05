# v2.1.26 only: prepared offline runtime, bounded write-free window, later acceptance.
# Deliver with hash-pinned legacy validation helpers OUTSIDE the live checkout.
param(
    [Parameter(Mandatory=$true)][ValidateSet('Prepare','Activate','Verify','Resume','Finalize')][string]$Stage,
    [Parameter(Mandatory=$true)][ValidateSet('v2.1.26')][string]$ReleaseTag,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory=$true)][ValidateSet('2e4fabdd10efab6350dea2f77029f08909f61af0')][string]$PreviousCommit,
    [Parameter(Mandatory=$true)][string]$Distribution,
    [switch]$InternalOnlyUnsignedRisk,
    [string]$RiskAcceptance,
    [string]$WorkflowId,
    [string]$ProjectRoot='C:\mto',
    [string]$EvidenceRoot='C:\ProgramData\MTO\release-workflows'
)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest

function Import-PinnedFunctions {
    param([string]$Path,[string]$Hash,[string[]]$Names)
    $sha=[Security.Cryptography.SHA256]::Create();$stream=$null
    try{$stream=[IO.File]::OpenRead($Path);$actual=[BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','')}
    finally{if($stream){$stream.Dispose()};$sha.Dispose()}
    if($actual -cne $Hash){throw 'Pinned validation helper changed.'}
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($Path,[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'Validation helper parse failed.'}
    $found=@()
    foreach($definition in $ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst]},$false)){
        if($definition.Name -cin $Names){
            # Export definitions only; never execute either legacy script's main body.
            Set-Item -Path ('Function:script:'+$definition.Name) -Value ([scriptblock]::Create($definition.Body.Extent.Text.TrimStart('{').TrimEnd('}')))
            $found+=$definition.Name
        }
    }
    if($found.Count -ne $Names.Count -or @(Compare-Object $Names $found).Count){throw 'Validation definitions missing.'}
}

function Write-NewWindowJson {
    param([string]$Path,$Value)
    Assert-NoLinkedPath $Path
    $bytes=(New-Object Text.UTF8Encoding($false)).GetBytes(($Value|ConvertTo-Json -Depth 20))
    $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try{$stream.Write($bytes,0,$bytes.Length);$stream.Flush($true)}finally{$stream.Dispose()}
}

function Assert-WindowEvidenceChild {
    param([string]$Path)
    Assert-NoLinkedPath $Path
    # Historical child folders inherit the protected workflow root's ACL.
    # Do not require inheritance to be disabled again, or alter existing ACLs.
    $acl=Get-Acl -LiteralPath $Path
    foreach($rule in $acl.Access){
        $sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
           $sid -cnotin @('S-1-5-18','S-1-5-32-544')){throw 'Unexpected historical evidence access rules.'}
    }
}

function Assert-AcceptedV225Predecessor {
    # Dynamic scope supplies the exact constants to read-only r2 validators.
    # Do NOT require the original strict workflow to become finalized.
    param([string]$Root)
    $source='2e4fabdd10efab6350dea2f77029f08909f61af0'
    $workflowId='v2.1.25-20261103T022136Z-76e90d6a'
    $continuationId='controlled-continuation-v2.1.25-20261103T063945Z-ef273f08'
    $evidence=Join-Path $Root $workflowId;$folder=Join-Path $evidence $continuationId
    $checkpointHash='72865023CB6913515ABE0C916609887DD5C5B47B026E4C5271E30F5D7100D33E'
    $riskHash='A55EA82304C412EC6C8DA2A78FEBDFE0CAC51E67C1C9D17BC93DA5CD0908D8FD'
    $reviewHelperHash='ECD80D3635AE9D049CD5174E766B2DD7A3366D3672954C258F4EA849109FB67F'
    $requiredFlags=@('--confirm-desktop-workflows','--confirm-update-and-reconnection','--confirm-isolated-restore-drill','--confirm-operations-ownership')
    $originalNames=@('workflow-state.json','baseline-before.json','audit-before.json',
        'checks-20261103T030944Z-9a2d46d1\baseline-final.json',
        'maintenance-payment-review-v2.1.25-20261103T045249Z-5f22064e\summary.json',
        'maintenance-payment-review-v2.1.25-20261103T045249Z-5f22064e\private-case.json',
        'maintenance-payment-review-v2.1.25-20261103T045249Z-5f22064e\current-capture.json',
        'maintenance-payment-review-v2.1.25-20261103T045249Z-5f22064e\current-reconciliation.json')
    Assert-NoLinkedPath $evidence;Assert-ProtectedEvidenceRoot $evidence
    Assert-WindowEvidenceChild $folder
    $completion=Join-Path $folder 'completion.json';Assert-NoLinkedPath $completion
    if((Get-WorkflowSha256 $completion) -cne '7D253C34FB2AB18E00D642F35457EEFFAEE0A00B66AB5905F579B902E19B0F95'){
        throw 'Exact accepted v2.1.25 completion evidence required.'
    }
    Assert-CompletedRecord (Read-Json $completion)
    $prior=Read-Json (Join-Path $evidence 'workflow-state.json')
    if($prior.status -cne 'BLOCKED' -or $prior.failure_stage -cne 'financial-compare' -or
       $prior.activation_completed -ne $true -or $prior.expected_commit -cne $source -or
       $prior.completed_utc -or $prior.manual_accepted_utc){throw 'Original v2.1.25 blocked state changed.'}
}

function Confirm-WindowAction {
    param([string]$Prompt,[string]$Required)
    if(([string](Read-Host $Prompt)).Trim() -cne $Required){throw 'Required approval was not supplied.'}
}

function Assert-WindowIdentity {
    param($State)
    if($State.format_version -ne 2 -or $State.release_tag -cne $ReleaseTag -or
       $State.expected_commit -cne $ExpectedCommit -or $State.previous_commit -cne $PreviousCommit -or
       $State.project_root -cne $script:ResolvedProject -or $State.distribution -cne $script:ResolvedDistribution -or
       $State.manifest_sha256 -cne $script:ManifestHash -or $State.risk_sha256 -cne $script:RiskHash -or
       $State.internal_only -ne [bool]$InternalOnlyUnsignedRisk -or
       $State.change_profile -cne 'FINANCIAL_ACCOUNT_ROUTING_NO_SCHEMA'){
        throw 'Bounded workflow identity changed.'
    }
}

function New-WindowAttempt {
    $attempt='checks-'+[datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
    $script:GateDirectory=Join-Path $script:RunDirectory $attempt
    Assert-NoLinkedPath $script:GateDirectory
    New-Item -ItemType Directory -Path $script:GateDirectory|Out-Null
    $script:WorkflowState.last_check_directory=$script:GateDirectory
    Write-WorkflowState $script:WorkflowState $script:StatePath
}

function Assert-WindowSnapshot {
    param([string]$Path,[string]$Hash)
    Assert-NoLinkedPath $Path
    if($Hash -cnotmatch '^[0-9A-F]{64}$' -or (Get-WorkflowSha256 $Path) -cne $Hash){throw 'Immutable window evidence changed.'}
}

function Assert-PreparedWheels {
    param($State)
    Assert-WindowSnapshot (Join-Path $script:RunDirectory 'target-lock.stdout.log') $State.target_lock_sha256
    $wheelRoot=Join-Path $script:RunDirectory 'wheels';Assert-NoLinkedPath $wheelRoot
    $files=@(Get-ChildItem -LiteralPath $wheelRoot -File)
    if(-not $files.Count -or $files.Count -ne @($State.wheel_sha256.PSObject.Properties).Count){throw 'Prepared wheel set changed.'}
    foreach($file in $files){
        if($file.Extension -cne '.whl'){throw 'Unexpected prepared dependency file.'}
        Assert-WindowSnapshot $file.FullName ([string]$State.wheel_sha256.($file.Name))
    }
    if(@(Get-ChildItem -LiteralPath $wheelRoot -Directory).Count){throw 'Unexpected dependency subdirectory.'}
}

function Invoke-WindowSnapshot {
    param([string]$Name,[switch]$CompareActivation)
    $output=Join-Path $script:GateDirectory ($Name+'.json')
    $arguments=@('-B','-m','scripts.capture_remediation_baseline','--database','--require-ready','--output',$output)
    if($CompareActivation){
        Assert-WindowSnapshot (Join-Path $script:RunDirectory 'baseline-before.json') $script:WorkflowState.baseline_sha256
        $arguments+=@('--compare-to',(Join-Path $script:RunDirectory 'baseline-before.json'))
    }
    Invoke-Gate $Name $arguments
    $value=Get-Content -LiteralPath $output -Raw|ConvertFrom-Json
    if(@($value.readiness_issues).Count){throw 'Current database/backup readiness failed.'}
    if($CompareActivation -and $value.comparison.financial_invariants_match -ne $true){throw 'Financial state changed inside the write-free window.'}
    return $output
}

function Invoke-WindowChecks {
    param([switch]$CompareActivation)
    Assert-Checkout $script:ResolvedProject $ExpectedCommit
    Assert-ReleaseIdentity $ReleaseTag $ExpectedCommit $script:ResolvedDistribution
    Invoke-Gate 'api-readiness' @('-B','-m','scripts.check_api_readiness','--timeout-seconds','120')
    Invoke-OperationsSmoke $script:ResolvedProject $script:Python
    $operations=Get-ChildItem -LiteralPath (Join-Path $script:ResolvedProject 'logs\operations') -Filter 'operations-health-*.json' -File|Sort-Object LastWriteTimeUtc -Descending|Select-Object -First 1
    if(-not $operations){throw 'Verified operations report missing.'}
    Assert-NoLinkedPath $operations.FullName
    [IO.File]::Copy($operations.FullName,(Join-Path $script:GateDirectory 'operations-health.json'),$false)
    Invoke-AuditGate 'audit-final'
    Invoke-Gate 'financial-reconciliation' @('-B','-m','scripts.phase6_financial_reconciliation_preflight','--require-ready','--output',(Join-Path $script:GateDirectory 'financial-reconciliation.json'))
    Invoke-Gate 'reliability' @('-B','-m','scripts.phase4_reliability_preflight','--require-ready','--output',(Join-Path $script:GateDirectory 'reliability.json'))
    Invoke-Gate 'dependencies' @('-B','-m','pip','check')
    $preflight=Join-Path $script:GateDirectory 'production-preflight.json'
    Invoke-Gate 'production-preflight' (Get-CertificationArguments $false $preflight)
    if((Get-Content -LiteralPath $preflight -Raw|ConvertFrom-Json).status -cne 'READY_FOR_MANUAL_ACCEPTANCE'){throw 'Current readiness is not acceptable.'}
    [void](Invoke-WindowSnapshot 'financial-check' -CompareActivation:$CompareActivation)
    Assert-Checkout $script:ResolvedProject $ExpectedCommit
}

function Get-WindowProofFiles {
    $hashes=[ordered]@{}
    foreach($file in @(Get-ChildItem -LiteralPath $script:GateDirectory -File)){
        Assert-NoLinkedPath $file.FullName;$hashes[$file.Name]=Get-WorkflowSha256 $file.FullName
    }
    return [pscustomobject]$hashes
}

function Invoke-WindowBridge {
    $script:WorkflowState.current_step='publisher-bridge'
    Write-WorkflowState $script:WorkflowState $script:StatePath
    Invoke-CheckedNative (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') @(
        '-NoProfile','-ExecutionPolicy','Bypass','-File',
        (Join-Path $script:ResolvedProject 'scripts\install_guarded_portal_task.ps1'),
        '-ExpectedCommit',$ExpectedCommit,'-ReleaseTag',$ReleaseTag,'-PreviousCommit',$PreviousCommit)
}

function Write-ActivationProof {
    $proofPath=Join-Path $script:GateDirectory 'activation-proof.json'
    Write-NewWindowJson $proofPath ([ordered]@{
        status='ACTIVATION_FINANCIAL_COMPARISON_PASS';workflow_id=$WorkflowId;expected_commit=$ExpectedCommit
        baseline_sha256=$script:WorkflowState.baseline_sha256;verified_utc=[datetime]::UtcNow.ToString('o')
        gate_sha256=(Get-WindowProofFiles)
    })
    $script:WorkflowState.activation_proof_path=(Split-Path -Leaf $script:GateDirectory)+'\activation-proof.json'
    $script:WorkflowState.activation_proof_sha256=Get-WorkflowSha256 $proofPath
    $script:WorkflowState.status='READY_FOR_ESSENTIAL_PILOT'
}

function Assert-ActivationProof {
    $path=Join-Path $script:RunDirectory $script:WorkflowState.activation_proof_path
    if($script:WorkflowState.activation_proof_path -cnotmatch '^checks-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}\\activation-proof.json$'){throw 'Unsafe activation proof path.'}
    Assert-WindowSnapshot $path $script:WorkflowState.activation_proof_sha256
    $proof=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($proof.status -cne 'ACTIVATION_FINANCIAL_COMPARISON_PASS' -or $proof.workflow_id -cne $WorkflowId -or
       $proof.expected_commit -cne $ExpectedCommit -or $proof.baseline_sha256 -cne $script:WorkflowState.baseline_sha256){throw 'Activation proof identity changed.'}
    Assert-WindowSnapshot (Join-Path $script:RunDirectory 'baseline-before.json') $proof.baseline_sha256
    Assert-WindowGateManifest $proof (Split-Path -Parent $path) -RequireComparison
    return $proof
}

function Assert-WindowGateManifest {
    param($Proof,[string]$Folder,[switch]$RequireComparison)
    $names=@($Proof.gate_sha256.PSObject.Properties|ForEach-Object{$_.Name})
    foreach($name in @('api-readiness.log','operations-health.json','audit-final.json','financial-reconciliation.json','reliability.json','dependencies.log','production-preflight.json','financial-check.json')){
        if($name -cnotin $names){throw 'Required window gate evidence missing.'}
    }
    foreach($entry in $Proof.gate_sha256.PSObject.Properties){
        if($entry.Name -cnotmatch '^[A-Za-z0-9_.-]+$'){throw 'Unsafe activation evidence filename.'}
        Assert-WindowSnapshot (Join-Path $Folder $entry.Name) $entry.Value
    }
    if($RequireComparison){
        $financial=Get-Content -LiteralPath (Join-Path $Folder 'financial-check.json') -Raw|ConvertFrom-Json
        if($financial.comparison.financial_invariants_match -ne $true -or @($financial.readiness_issues).Count){throw 'Window comparison proof did not pass.'}
    }
}

function Assert-ResumeProof {
    $path=Join-Path $script:RunDirectory 'resume.json'
    Assert-WindowSnapshot $path $script:WorkflowState.resume_sha256
    $proof=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($proof.status -cne 'FINANCIAL_ENTRY_MAY_RESUME' -or $proof.workflow_id -cne $WorkflowId -or
       $proof.expected_commit -cne $ExpectedCommit -or $proof.activation_proof_sha256 -cne $script:WorkflowState.activation_proof_sha256 -or
       $proof.baseline_sha256 -cne $script:WorkflowState.baseline_sha256 -or $proof.resumed_utc -cne $script:WorkflowState.resume_utc -or
       $proof.essential_read_only_client_pilot_confirmed -ne $true -or $proof.check_directory -cnotmatch '^checks-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$'){
        throw 'Explicit resume proof identity changed.'
    }
    Assert-WindowGateManifest $proof (Join-Path $script:RunDirectory $proof.check_directory) -RequireComparison
}

function Assert-WindowCompletion {
    $path=Join-Path $script:RunDirectory 'completion.json'
    Assert-WindowSnapshot $path $script:WorkflowState.completion_sha256
    $proof=Get-Content -LiteralPath $path -Raw|ConvertFrom-Json
    if($proof.status -cnotin @('PASS','PASS_WITH_ACCEPTED_RISK') -or $proof.workflow_id -cne $WorkflowId -or
       $proof.expected_commit -cne $ExpectedCommit -or $proof.activation_proof_sha256 -cne $script:WorkflowState.activation_proof_sha256 -or
       $proof.resume_sha256 -cne $script:WorkflowState.resume_sha256 -or $proof.completed_utc -cne $script:WorkflowState.completed_utc -or
       $proof.comparison_scope -cne 'UNCHANGED_DURING_RELEASE_WINDOW_ONLY' -or $proof.original_baseline_preserved -ne $true -or
       $proof.financial_activity_after_resume_not_attributed -ne $true -or $proof.acceptance_check_directory -cnotmatch '^checks-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$'){
        throw 'Completion scope or identity changed.'
    }
    $folder=Join-Path $script:RunDirectory $proof.acceptance_check_directory
    Assert-WindowGateManifest $proof $folder
    Assert-WindowSnapshot (Join-Path $folder 'manual-acceptance.json') $proof.manual_acceptance_sha256
    return $proof
}

function Read-BoundedManualAcceptance {
    $requirements=[ordered]@{
        '--confirm-desktop-workflows'='Full pilot workflows, duplicate-account isolation and PDF/Excel exports passed.'
        '--confirm-update-and-reconnection'='The matching verified client was installed and reconnected.'
        '--confirm-isolated-restore-drill'='An actual isolated restore drill and its integrity evidence were reviewed.'
        '--confirm-operations-ownership'='Named operators accepted maintenance and escalation responsibilities.'
    }
    Write-Host 'Financial entry was explicitly resumed. This accepts current controls and pilot evidence, not unchanged totals across later business activity.'
    foreach($entry in $requirements.GetEnumerator()){
        Write-Host $entry.Value;Confirm-WindowAction ('Type ACCEPT '+$ReleaseTag) ('ACCEPT '+$ReleaseTag)
    }
    return @($requirements.Keys)
}

$legacy=Join-Path $PSScriptRoot 'workflow_legacy_v1.ps1'
Import-PinnedFunctions $legacy 'EFD7761A37EE99A2B510B3D5A2BEA306B1F2FFF6D74F1B7E6C41EA2B4830DC67' @(
    'Invoke-CheckedNative','Get-CheckedGit','Get-WorkflowSha256','ConvertTo-NativeArgument','Invoke-CapturedNative',
    'Assert-NoLinkedPath','Assert-ProtectedEvidenceRoot','Assert-Checkout','Assert-ReleaseIdentity',
    'Write-WorkflowState','Invoke-Gate','Invoke-AuditGate','Invoke-OperationsSmoke','Get-CertificationArguments','Enter-PortalPublisherMaintenanceLock')
Import-PinnedFunctions (Join-Path $PSScriptRoot 'v225_checkpoint_validation.ps1') 'ECD80D3635AE9D049CD5174E766B2DD7A3366D3672954C258F4EA849109FB67F' @(
    'Read-Json','Assert-OriginalEvidence')
Import-PinnedFunctions (Join-Path $PSScriptRoot 'v225_acceptance_validation.ps1') '74380889C60D38D2CEFFBAEE752DD16C2030AE787C1490A5CFB60B74D30AEF24' @(
    'Assert-Phase9','Assert-PreparedReview','Assert-CurrentApprovalRecord','Assert-ManualRecord','Get-SafeEvidencePath','Assert-CompletedRecord')

$script:ResolvedProject=[IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$script:ResolvedDistribution=(Resolve-Path -LiteralPath $Distribution).Path.TrimEnd('\')
$resolvedEvidence=[IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
foreach($path in @($script:ResolvedProject,$script:ResolvedDistribution,$resolvedEvidence,$legacy)){Assert-NoLinkedPath $path}
if($resolvedEvidence -eq [IO.Path]::GetPathRoot($resolvedEvidence).TrimEnd('\') -or
   $resolvedEvidence.StartsWith($script:ResolvedProject+'\',[StringComparison]::OrdinalIgnoreCase) -or
   $resolvedEvidence.Equals($script:ResolvedProject,[StringComparison]::OrdinalIgnoreCase)){throw 'Use protected evidence outside the live checkout.'}
$principal=New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Administrator console required.'}
$script:Python=Join-Path $script:ResolvedProject 'venv\Scripts\python.exe'
$script:ResolvedRisk='';$script:RiskHash=''
if($InternalOnlyUnsignedRisk){
    $script:ResolvedRisk=(Resolve-Path -LiteralPath $RiskAcceptance).Path;Assert-NoLinkedPath $script:ResolvedRisk
    $script:RiskHash=Get-WorkflowSha256 $script:ResolvedRisk
    if($script:RiskHash -cne 'A55EA82304C412EC6C8DA2A78FEBDFE0CAC51E67C1C9D17BC93DA5CD0908D8FD'){throw 'This profile does not authorize a changed or extended risk exception.'}
}elseif($RiskAcceptance){throw 'Risk file requires explicit internal-only mode.'}
$script:ManifestHash=Get-WorkflowSha256 (Join-Path $script:ResolvedDistribution 'release-manifest.json')
if(-not (Test-Path -LiteralPath $resolvedEvidence -PathType Container)){throw 'Existing protected workflow evidence root required.'}
Assert-ProtectedEvidenceRoot $resolvedEvidence
if(-not $WorkflowId){
    if($Stage -cne 'Prepare'){throw 'Use the WorkflowId printed by Prepare.'}
    $WorkflowId=$ReleaseTag+'-'+[datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ')+'-'+[guid]::NewGuid().ToString('N').Substring(0,8)
}
if($WorkflowId -cnotmatch '^v2\.1\.26-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$'){throw 'Invalid v2.1.26 workflow identity.'}
$script:RunDirectory=Join-Path $resolvedEvidence $WorkflowId
$script:StatePath=Join-Path $script:RunDirectory 'workflow-state.json'
$script:WorkflowState=$null;$script:MayWriteState=$false;$lock=$null;$pushed=$false
$oldOverride=[Environment]::GetEnvironmentVariable('MTO_PROJECT_ROOT','Process')
try{
    Assert-NoLinkedPath (Join-Path $resolvedEvidence 'workflow.lock')
    $lock=[IO.File]::Open((Join-Path $resolvedEvidence 'workflow.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::None)
    $env:MTO_PROJECT_ROOT=$script:ResolvedProject;Push-Location -LiteralPath $script:ResolvedProject;$pushed=$true
    Assert-ReleaseIdentity $ReleaseTag $ExpectedCommit $script:ResolvedDistribution
    if($Stage -ceq 'Prepare'){
        Assert-Checkout $script:ResolvedProject $PreviousCommit
        Assert-AcceptedV225Predecessor $resolvedEvidence
        if(Test-Path -LiteralPath $script:RunDirectory){throw 'Prepare never overwrites prior attempts; start a new Prepare workflow.'}
        # This bounded profile is not valid for runtime/schema migrations.
        foreach($material in @('requirements.txt','requirements.lock','migration_manager.py','backend/models.py')){
            if((Get-CheckedGit @('rev-parse',($PreviousCommit+':'+$material))) -cne (Get-CheckedGit @('rev-parse',($ExpectedCommit+':'+$material)))){throw 'Runtime/schema changes require a separately reviewed release profile.'}
        }
        if(Get-CheckedGit @('diff','--name-only',$PreviousCommit,$ExpectedCommit,'--','migrations')){throw 'Schema migrations require a separate release profile.'}
        New-Item -ItemType Directory -Path $script:RunDirectory|Out-Null
        Invoke-CheckedNative 'icacls.exe' @($script:RunDirectory,'/inheritance:r','/grant:r','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F')
        $script:WorkflowState=[ordered]@{
            format_version=2;release_tag=$ReleaseTag;expected_commit=$ExpectedCommit;previous_commit=$PreviousCommit
            project_root=$script:ResolvedProject;distribution=$script:ResolvedDistribution;internal_only=[bool]$InternalOnlyUnsignedRisk
            manifest_sha256=$script:ManifestHash;risk_sha256=$script:RiskHash;change_profile='FINANCIAL_ACCOUNT_ROUTING_NO_SCHEMA'
            status='PREPARING';current_step='';failure_stage='';last_check_directory='';activation_completed=$false
            baseline_sha256='';target_lock_sha256='';wheel_sha256=@{};activation_proof_path='';activation_proof_sha256=''
            window_started_utc='';resume_utc='';resume_sha256='';manual_accepted_utc='';completed_utc='';completion_sha256=''
        }
        $script:MayWriteState=$true
        Write-WorkflowState $script:WorkflowState $script:StatePath;New-WindowAttempt
        Write-Host 'PREPARATION ONLY. Continue normal office entry. No backup, restart or activation in this stage.'
        Invoke-Gate 'readiness' @('-B','-m','scripts.phase4_reliability_preflight','--require-ready','--output',(Join-Path $script:GateDirectory 'readiness.json'))
        Invoke-AuditGate 'audit-before'
        Invoke-Gate 'financial-before' @('-B','-m','scripts.phase6_financial_reconciliation_preflight','--require-ready','--output',(Join-Path $script:GateDirectory 'financial-before.json'))
        $protocolCheck=@'
import ast, json, subprocess, sys
def constants(commit):
    raw = subprocess.check_output(['git', 'show', commit + ':mto_version.py'])
    result = {}
    for node in ast.parse(raw).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value.value
    return result
before, after = constants(sys.argv[1]), constants(sys.argv[2])
if after['PRODUCT_VERSION'] != sys.argv[3][1:]:
    raise RuntimeError('Target product identity differs')
for key in ('API_VERSION', 'MIN_CLIENT_VERSION'):
    if before[key] != after[key]:
        raise RuntimeError('Protocol changes require another maintenance profile')
print(json.dumps({'status': 'PROTOCOL_CONTRACT_UNCHANGED', 'api_version': after['API_VERSION'], 'min_client_version': after['MIN_CLIENT_VERSION']}))
'@
        Invoke-Gate 'protocol-compatibility' @('-B','-c',$protocolCheck,$PreviousCommit,$ExpectedCommit,$ReleaseTag)
        $capture=Join-Path $script:RunDirectory 'target-lock'
        if((Invoke-CapturedNative 'git' @('show',($ExpectedCommit+':requirements.lock')) $capture) -ne 0){throw 'Target dependency lock capture failed.'}
        $script:WorkflowState.target_lock_sha256=Get-WorkflowSha256 (Join-Path $script:RunDirectory 'target-lock.stdout.log')
        $wheels=Join-Path $script:RunDirectory 'wheels';New-Item -ItemType Directory -Path $wheels|Out-Null
        Invoke-Gate 'dependency-download' @('-B','-m','pip','download','--require-hashes','--only-binary=:all:','--dest',$wheels,'-r',(Join-Path $script:RunDirectory 'target-lock.stdout.log'))
        $wheelUri=([Uri]($wheels+'\')).AbsoluteUri
        Invoke-Gate 'offline-install-plan' @('-B','-m','pip','install','--dry-run','--ignore-installed','--require-hashes','--no-index','--find-links',$wheelUri,'-r',(Join-Path $script:RunDirectory 'target-lock.stdout.log'))
        $hashes=[ordered]@{};foreach($file in @(Get-ChildItem -LiteralPath $wheels -File)){$hashes[$file.Name]=Get-WorkflowSha256 $file.FullName}
        $script:WorkflowState.wheel_sha256=[pscustomobject]$hashes
        $script:WorkflowState.status='PREPARED';Write-WorkflowState $script:WorkflowState $script:StatePath
    }else{
        Assert-NoLinkedPath $script:StatePath;Assert-ProtectedEvidenceRoot $script:RunDirectory
        $script:WorkflowState=Get-Content -LiteralPath $script:StatePath -Raw|ConvertFrom-Json
        Assert-WindowIdentity $script:WorkflowState
        if($Stage -ceq 'Finalize' -and (Test-Path -LiteralPath (Join-Path $script:RunDirectory 'completion.json'))){throw 'Acceptance is already recorded. Use Verify; do not repeat Finalize.'}
        if($Stage -ceq 'Activate'){
            if($script:WorkflowState.status -cne 'PREPARED' -or $script:WorkflowState.activation_completed){throw 'Only an untouched prepared workflow can activate once.'}
            Assert-Checkout $script:ResolvedProject $PreviousCommit;Assert-AcceptedV225Predecessor $resolvedEvidence
            Assert-PreparedWheels $script:WorkflowState
            $script:MayWriteState=$true
            New-WindowAttempt
            Invoke-Gate 'readiness-now' @('-B','-m','scripts.phase4_reliability_preflight','--require-ready','--output',(Join-Path $script:GateDirectory 'readiness-now.json'))
            Confirm-WindowAction ('Pause ALL financial entry. Type BEGIN MTO RELEASE '+$ReleaseTag) ('BEGIN MTO RELEASE '+$ReleaseTag)
            $script:WorkflowState.window_started_utc=[datetime]::UtcNow.ToString('o')
            Invoke-Gate 'backup' @('-B','-c',"import asyncio; from backend.services.backup_service import run_hybrid_backup; ok,msg=asyncio.run(run_hybrid_backup(user={'id':0,'username':'approved-release-workflow','role':'admin'})); print({'success':ok,'message':msg}); raise SystemExit(0 if ok else 2)")
            Invoke-Gate 'baseline-before' @('-B','-m','scripts.capture_remediation_baseline','--database','--require-ready','--output',(Join-Path $script:RunDirectory 'baseline-before.json'))
            $script:WorkflowState.baseline_sha256=Get-WorkflowSha256 (Join-Path $script:RunDirectory 'baseline-before.json')
            $script:WorkflowState.status='ACTIVATING';$script:WorkflowState.current_step='immutable-updater'
            Write-WorkflowState $script:WorkflowState $script:StatePath
            $pipNames=@('PIP_NO_INDEX','PIP_FIND_LINKS','PIP_NO_INPUT','PIP_DISABLE_PIP_VERSION_CHECK');$oldPip=@{}
            foreach($name in $pipNames){$oldPip[$name]=[Environment]::GetEnvironmentVariable($name,'Process')}
            $publisherLock=$null
            try{
                $env:PIP_NO_INDEX='1';$env:PIP_NO_INPUT='1';$env:PIP_DISABLE_PIP_VERSION_CHECK='1'
                $env:PIP_FIND_LINKS=([Uri]((Join-Path $script:RunDirectory 'wheels')+'\')).AbsoluteUri
                $publisherLock=Enter-PortalPublisherMaintenanceLock
                $updaterArguments=@('-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $script:ResolvedProject 'scripts\apply_immutable_release.ps1'),'-Apply','-ReleaseTag',$ReleaseTag,'-Distribution',$script:ResolvedDistribution,'-ProjectRoot',$script:ResolvedProject)
                if($InternalOnlyUnsignedRisk){$updaterArguments+=@('-InternalOnlyUnsignedRisk','-RiskAcceptance',$script:ResolvedRisk)}
                Invoke-CheckedNative (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') $updaterArguments
            }finally{
                if($publisherLock){$publisherLock.Unlock(0,1);$publisherLock.Dispose()}
                foreach($name in $pipNames){[Environment]::SetEnvironmentVariable($name,$oldPip[$name],'Process')}
            }
            $script:WorkflowState.activation_completed=$true;Write-WorkflowState $script:WorkflowState $script:StatePath
            Invoke-WindowBridge
            Invoke-WindowChecks -CompareActivation
            Write-ActivationProof
        }else{
            if(-not $script:WorkflowState.activation_completed){throw 'Activation is not confirmed; review updater evidence. Never repeat Activate blindly.'}
            Assert-Checkout $script:ResolvedProject $ExpectedCommit
            $resumed=-not [string]::IsNullOrWhiteSpace($script:WorkflowState.resume_utc)
            if($Stage -ceq 'Resume' -and $resumed){throw 'Entry already resumed; use Verify or Finalize.'}
            if($Stage -ceq 'Finalize' -and -not $resumed){throw 'An explicit successful Resume checkpoint is required before later acceptance.'}
            if($script:WorkflowState.activation_proof_path){
                [void](Assert-ActivationProof)
            }elseif($Stage -ceq 'Verify' -and -not $resumed){
                # Recover failed post-activation gates, never rerun the updater.
                Assert-WindowSnapshot (Join-Path $script:RunDirectory 'baseline-before.json') $script:WorkflowState.baseline_sha256
            }else{throw 'Successful activation checks are required before Resume or acceptance. Use Verify while entry remains paused.'}
            $script:MayWriteState=$true
            New-WindowAttempt
            if($Stage -ceq 'Resume'){
                if($script:WorkflowState.resume_utc){throw 'Entry already resumed; use Verify or Finalize.'}
                $script:WorkflowState.current_step='essential-client-pilot'
                Write-WorkflowState $script:WorkflowState $script:StatePath
                Write-Host 'Keep entry paused. Perform the essential client pilot using READ-ONLY views/target preview; do not save a test production payment.'
                Confirm-WindowAction ('Type CONFIRM ESSENTIAL CLIENT PILOT '+$ReleaseTag) ('CONFIRM ESSENTIAL CLIENT PILOT '+$ReleaseTag)
                Invoke-WindowChecks -CompareActivation
                $resumedUtc=[datetime]::UtcNow.ToString('o')
                $resumePath=Join-Path $script:RunDirectory 'resume.json'
                Write-NewWindowJson $resumePath ([ordered]@{status='FINANCIAL_ENTRY_MAY_RESUME';workflow_id=$WorkflowId;expected_commit=$ExpectedCommit;activation_proof_sha256=$script:WorkflowState.activation_proof_sha256;baseline_sha256=$script:WorkflowState.baseline_sha256;resumed_utc=$resumedUtc;essential_read_only_client_pilot_confirmed=$true;check_directory=(Split-Path -Leaf $script:GateDirectory);gate_sha256=(Get-WindowProofFiles)})
                $script:WorkflowState.resume_sha256=Get-WorkflowSha256 $resumePath
                $script:WorkflowState.resume_utc=$resumedUtc
                $script:WorkflowState.status='ENTRY_RESUMED_PENDING_ACCEPTANCE'
            }else{
                if($resumed){Assert-ResumeProof}
                if(-not $resumed){Invoke-WindowBridge}
                Invoke-WindowChecks -CompareActivation:(-not $resumed)
                if($Stage -ceq 'Finalize'){
                    $script:WorkflowState.current_step='manual-acceptance'
                    Write-WorkflowState $script:WorkflowState $script:StatePath
                    $flags=@(Read-BoundedManualAcceptance)
                    $manualPath=Join-Path $script:GateDirectory 'manual-acceptance.json'
                    Write-NewWindowJson $manualPath ([ordered]@{workflow_id=$WorkflowId;accepted_utc=[datetime]::UtcNow.ToString('o');manual_flags=$flags;scope='PILOT_AND_CURRENT_CONTROLS_AFTER_EXPLICIT_RESUME';unchanged_totals_since_predeployment_claimed=$false})
                    $finalPath=Join-Path $script:GateDirectory 'production-final.json'
                    Invoke-Gate 'production-final' (@(Get-CertificationArguments $true $finalPath)+$flags)
                    $final=Get-Content -LiteralPath $finalPath -Raw|ConvertFrom-Json
                    if($final.status -cnotin @('PASS','PASS_WITH_ACCEPTED_RISK')){throw 'Final readiness rejected acceptance.'}
                    [void](Assert-ActivationProof);Assert-ResumeProof
                    Assert-Checkout $script:ResolvedProject $ExpectedCommit
                    Assert-ReleaseIdentity $ReleaseTag $ExpectedCommit $script:ResolvedDistribution
                    $script:WorkflowState.manual_accepted_utc=[datetime]::UtcNow.ToString('o');$script:WorkflowState.completed_utc=$script:WorkflowState.manual_accepted_utc
                    $script:WorkflowState.status=$final.status
                    Write-NewWindowJson (Join-Path $script:RunDirectory 'completion.json') ([ordered]@{status=$final.status;workflow_id=$WorkflowId;expected_commit=$ExpectedCommit;completed_utc=$script:WorkflowState.completed_utc;activation_proof_sha256=$script:WorkflowState.activation_proof_sha256;resume_sha256=$script:WorkflowState.resume_sha256;manual_acceptance_sha256=(Get-WorkflowSha256 $manualPath);acceptance_check_directory=(Split-Path -Leaf $script:GateDirectory);gate_sha256=(Get-WindowProofFiles);comparison_scope='UNCHANGED_DURING_RELEASE_WINDOW_ONLY';financial_activity_after_resume_not_attributed=$true;original_baseline_preserved=$true})
                    $script:WorkflowState.completion_sha256=Get-WorkflowSha256 (Join-Path $script:RunDirectory 'completion.json')
                }else{
                    if($script:WorkflowState.completed_utc){
                        $script:WorkflowState.status=(Assert-WindowCompletion).status
                    }elseif(-not $resumed){
                        Write-ActivationProof
                    }else{
                        $script:WorkflowState.status='ENTRY_RESUMED_PENDING_ACCEPTANCE'
                    }
                }
            }
        }
        Write-WorkflowState $script:WorkflowState $script:StatePath
    }
    Write-Host ('MTO BOUNDED RELEASE: '+$script:WorkflowState.status)
    Write-Host ('WorkflowId: '+$WorkflowId);Write-Host ('Evidence: '+$script:RunDirectory)
    if($script:WorkflowState.resume_utc){Write-Host 'Financial entry was explicitly authorized to resume. Later acceptance does not claim unchanged totals across business activity.'}
    elseif($script:WorkflowState.activation_completed){Write-Host 'Keep entry paused through the essential read-only client pilot and successful Resume.'}
    else{Write-Host 'Preparation only; no office pause requested yet. Activation requires a separately approved maintenance window.'}
}catch{
    if($script:MayWriteState -and $null -ne $script:WorkflowState){
        $script:WorkflowState.failure_stage=$script:WorkflowState.current_step
        $script:WorkflowState.status=if($script:WorkflowState.resume_utc){'BLOCKED_POST_RESUME'}else{'BLOCKED'}
        Write-WorkflowState $script:WorkflowState $script:StatePath
    }
    Write-Host 'BLOCKED. Preserve all evidence. No helper-initiated rollback, cleanup, data repair or baseline replacement.'
    Write-Host 'If entry had resumed, review the failing current control under incident procedures; never roll back over later payments.'
    throw
}finally{
    if($pushed){Pop-Location};[Environment]::SetEnvironmentVariable('MTO_PROJECT_ROOT',$oldOverride,'Process')
    if($lock){$lock.Dispose()}
}
