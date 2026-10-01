# Orchestrates the existing approved gates; does not replace the immutable updater.
# Deliver outside the production checkout with a release-specific, hash-verified launcher.
param(
    [Parameter(Mandatory = $true)][ValidateSet('Activate', 'Verify', 'Finalize')][string]$Stage,
    [Parameter(Mandatory = $true)][ValidatePattern('^v\d+\.\d+\.\d+$')][string]$ReleaseTag,
    [Parameter(Mandatory = $true)][string]$Distribution,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedCommit,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$PreviousCommit,
    [switch]$InternalOnlyUnsignedRisk,
    [string]$RiskAcceptance,
    [string]$WorkflowId,
    [string]$ProjectRoot = 'C:\mto',
    [string]$EvidenceRoot = 'C:\ProgramData\MTO\release-workflows'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Invoke-CheckedNative {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

function Get-CheckedGit {
    param([string[]]$Arguments)
    $result = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw 'Git identity check failed.' }
    return ($result | Out-String).Trim()
}

function Get-WorkflowSha256 {
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = [IO.File]::OpenRead($Path)
        return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
    } finally {
        if ($stream) { $stream.Dispose() }
        $sha.Dispose()
    }
}

function Assert-NoLinkedPath {
    param([string]$Path)
    $candidate = [IO.Path]::GetFullPath($Path)
    while ($candidate) {
        if (Test-Path -LiteralPath $candidate) {
            $item = Get-Item -LiteralPath $candidate -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'Release workflow paths must not contain linked items.'
            }
        }
        $candidate = Split-Path -Parent $candidate
    }
}

function Assert-ProtectedEvidenceRoot {
    param([string]$Path)
    $acl = Get-Acl -LiteralPath $Path
    if (-not $acl.AreAccessRulesProtected) { throw 'Release evidence root must have protected access rules.' }
    $allowed = @('S-1-5-18', 'S-1-5-32-544')
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $sid -notin $allowed) {
            throw 'Release evidence root permits unexpected access. Review its ACL; no existing permissions were changed.'
        }
    }
}

function Assert-Checkout {
    param([string]$Root, [string]$RequiredCommit)
    if ((Get-CheckedGit @('branch', '--show-current')) -ne 'master') {
        throw 'Production must be on master.'
    }
    if ((Get-CheckedGit @('status', '--porcelain', '--untracked-files=all'))) {
        throw 'Production contains local changes. Inspect them; this helper will not delete anything.'
    }
    $gitRoot = [IO.Path]::GetFullPath((Get-CheckedGit @('rev-parse', '--show-toplevel'))).TrimEnd('\')
    if (-not $gitRoot.Equals($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unexpected checkout root.'
    }
    $origin = (Get-CheckedGit @('remote', 'get-url', 'origin')).TrimEnd('/').ToLowerInvariant()
    if ($origin.EndsWith('.git')) { $origin = $origin.Substring(0, $origin.Length - 4) }
    if ($origin -ne 'https://github.com/tibintibin01/mto') { throw 'Unexpected Git origin.' }
    if ((Get-CheckedGit @('rev-parse', 'HEAD')) -ne $RequiredCommit) {
        throw 'Active production source does not match the required commit for this stage.'
    }
}

function Assert-ReleaseIdentity {
    param([string]$Tag, [string]$Commit, [string]$Package)
    if ((Get-CheckedGit @('rev-parse', ($Tag + '^{commit}'))) -ne $Commit -or
        (Get-CheckedGit @('rev-parse', 'refs/remotes/origin/master')) -ne $Commit) {
        throw 'Approved tag and local origin/master must match the expected release commit.'
    }
    $manifest = Get-Content -LiteralPath (Join-Path $Package 'release-manifest.json') -Raw | ConvertFrom-Json
    if ($manifest.version -ne $Tag -or $manifest.source_commit -ne $Commit -or
        $manifest.product_version -ne $Tag.Substring(1) -or $manifest.material_hash_mode -ne 'git-blob-sha256') {
        throw 'Release manifest identity mismatch.'
    }
    # Full allowlist, hashes, signing/risk and dependency checks remain in the updater and Phase 9.
}

function Write-WorkflowState {
    param($State, [string]$Path)
    $temporary = $Path + '.tmp'
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Assert-ResumeState {
    param($State, [string]$Tag, [string]$Commit, [string]$BeforeCommit,
          [string]$Root, [string]$Package, [bool]$Internal, [string]$RiskHash,
          [string]$ManifestHash)
    if ($State.format_version -ne 1 -or $State.release_tag -ne $Tag -or
        $State.expected_commit -ne $Commit -or $State.previous_commit -ne $BeforeCommit -or
        $State.project_root -ne $Root -or $State.distribution -ne $Package -or
        $State.internal_only -ne $Internal -or $State.risk_sha256 -ne $RiskHash -or
        $State.manifest_sha256 -ne $ManifestHash -or -not $State.activation_completed) {
        throw 'Workflow identity mismatch or activation was not confirmed complete. Review protected updater evidence.'
    }
}

function Invoke-Gate {
    param([string]$Name, [string[]]$Arguments)
    $script:WorkflowState.current_step = $Name
    Write-WorkflowState $script:WorkflowState $script:StatePath
    $log = Join-Path $script:GateDirectory ($Name + '.log')
    Write-Host "Checking $Name..."
    & $script:Python @Arguments *> $log
    if ($LASTEXITCODE -ne 0) {
        throw "$Name blocked (exit $LASTEXITCODE). Full output retained: $log"
    }
    Write-Host "$Name`: PASS"
}

function Invoke-AuditGate {
    param([string]$Name)
    Invoke-Gate $Name @('-m', 'scripts.phase5_audit_observability_preflight',
        '--require-ready', '--require-active', '--require-live-event',
        '--output', (Join-Path $script:RunDirectory ($Name + '.json')))
}

function Invoke-OperationsSmoke {
    param([string]$Root, [string]$PythonPath)
    $name = 'MTO Operations Health Check'
    $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
    $actions = @($task.Actions)
    if ($actions.Count -ne 1 -or
        -not ([IO.Path]::GetFullPath($actions[0].Execute.Trim('"'))).Equals($PythonPath, [StringComparison]::OrdinalIgnoreCase) -or
        $actions[0].Arguments.Trim() -ne '-m scripts.run_operations_health_check --retention-days 400' -or
        -not ([IO.Path]::GetFullPath($actions[0].WorkingDirectory)).TrimEnd('\').Equals($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Operations task action does not match the approved runner.'
    }
    $deadline = (Get-Date).AddMinutes(5)
    while ([string]$task.State -eq 'Running') {
        if ((Get-Date) -ge $deadline) { throw 'Existing operations check did not finish.' }
        Start-Sleep -Seconds 2
        $task = Get-ScheduledTask -TaskName $name
    }
    if ([string]$task.State -ne 'Ready') { throw 'Operations task is not ready.' }
    $before = [datetime](Get-ScheduledTaskInfo -TaskName $name).LastRunTime
    # Scheduled-task timestamps have second precision. Avoid triggering twice
    # in the same second and mistaking a real new run for the previous run.
    Start-Sleep -Seconds 2
    $startedUtc = [datetime]::UtcNow
    Start-ScheduledTask -TaskName $name
    $deadline = (Get-Date).AddMinutes(5)
    do {
        Start-Sleep -Seconds 2
        $task = Get-ScheduledTask -TaskName $name
        $info = Get-ScheduledTaskInfo -TaskName $name
        $finished = ([string]$task.State -eq 'Ready' -and [datetime]$info.LastRunTime -gt $before)
    } while (-not $finished -and (Get-Date) -lt $deadline)
    if (-not $finished) { throw 'Operations check did not finish within five minutes.' }
    if ([int64]$info.LastTaskResult -ne 0) {
        throw "Operations check failed with result $($info.LastTaskResult). Review logs\operations; no gate was skipped."
    }
    $report = Get-ChildItem -LiteralPath (Join-Path $Root 'logs\operations') -Filter 'operations-health-*.json' -File |
        Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
    if (-not $report -or $report.LastWriteTimeUtc -lt $startedUtc) {
        throw 'A fresh operations-health report was not found.'
    }
    $payload = Get-Content -LiteralPath $report.FullName -Raw | ConvertFrom-Json
    $capturedUtc = [datetime]::Parse($payload.timestamp_utc).ToUniversalTime()
    if ($payload.report_type -ne 'MTO_OPERATIONS_HEALTH' -or $payload.status -ne 'PASS' -or
        $capturedUtc -lt $startedUtc -or $capturedUtc -gt [datetime]::UtcNow.AddSeconds(30)) {
        throw 'Fresh operations-health report did not pass.'
    }
    Write-Host 'operations-smoke: PASS'
}

function Get-CertificationArguments {
    param([bool]$Final, [string]$Output)
    $mode = if ($Final) { '--final' } else { '--preflight' }
    $arguments = @('-m', 'scripts.phase9_production_readiness_certification', $mode,
        '--distribution', $script:ResolvedDistribution, '--output', $Output)
    if ($InternalOnlyUnsignedRisk) {
        $arguments += @('--distribution-scope', 'internal-municipal', '--risk-acceptance', $script:ResolvedRisk)
    }
    return $arguments
}

function Invoke-PostChecks {
    Assert-Checkout $script:ResolvedProject $ExpectedCommit
    Assert-ReleaseIdentity $ReleaseTag $ExpectedCommit $script:ResolvedDistribution
    # Retain each attempt instead of overwriting evidence from an earlier failed run.
    $attempt = 'checks-' + [datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
    $script:GateDirectory = Join-Path $script:RunDirectory $attempt
    New-Item -ItemType Directory -Path $script:GateDirectory | Out-Null
    $script:WorkflowState.last_check_directory = $script:GateDirectory
    Write-WorkflowState $script:WorkflowState $script:StatePath
    Invoke-Gate 'api-readiness' @('-m', 'scripts.check_api_readiness', '--timeout-seconds', '120')
    $script:WorkflowState.current_step = 'operations-smoke'
    Write-WorkflowState $script:WorkflowState $script:StatePath
    Invoke-OperationsSmoke $script:ResolvedProject $script:Python
    Invoke-AuditGate 'audit-final'
    $preflightPath = Join-Path $script:GateDirectory 'production-preflight.json'
    Invoke-Gate 'production-preflight' (Get-CertificationArguments $false $preflightPath)
    $preflight = Get-Content -LiteralPath $preflightPath -Raw | ConvertFrom-Json
    if ($preflight.status -ne 'READY_FOR_MANUAL_ACCEPTANCE') { throw 'Phase 9 is not ready for manual acceptance.' }
    Invoke-Gate 'financial-compare' @('-m', 'scripts.capture_remediation_baseline', '--database',
        '--require-ready', '--compare-to', (Join-Path $script:RunDirectory 'baseline-before.json'),
        '--output', (Join-Path $script:GateDirectory 'baseline-final.json'))
    Invoke-Gate 'dependencies' @('-m', 'pip', 'check')
    Assert-Checkout $script:ResolvedProject $ExpectedCommit
}

function Read-ManualAcceptance {
    param([string]$Tag)
    $requirements = [ordered]@{
        '--confirm-desktop-workflows' = 'Pilot client workflows, duplicate-account isolation, and PDF/Excel exports passed.'
        '--confirm-update-and-reconnection' = 'Correct client installer was verified, installed, and reconnected after the server update.'
        '--confirm-isolated-restore-drill' = 'An isolated restore drill and its checksum/integrity evidence have been reviewed and accepted.'
        '--confirm-operations-ownership' = 'Named operators accepted the maintenance and escalation responsibilities.'
    }
    foreach ($entry in $requirements.GetEnumerator()) {
        Write-Host $entry.Value
        $confirmation = Read-Host "Type ACCEPT $Tag or press Enter to stop"
        if ($confirmation -cne "ACCEPT $Tag") {
            throw 'Manual acceptance not supplied. Automated checks do not substitute for the client pilot or restore evidence.'
        }
    }
    return @($requirements.Keys)
}

$script:ResolvedProject = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$script:ResolvedDistribution = (Resolve-Path -LiteralPath $Distribution -ErrorAction Stop).Path.TrimEnd('\')
$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
if ($resolvedEvidence -eq [IO.Path]::GetPathRoot($resolvedEvidence).TrimEnd('\')) {
    throw 'Use a dedicated release-workflows directory, not a drive root.'
}
foreach ($path in @($script:ResolvedProject, $script:ResolvedDistribution, $resolvedEvidence)) {
    Assert-NoLinkedPath $path
}
if ($resolvedEvidence.Equals($script:ResolvedProject, [StringComparison]::OrdinalIgnoreCase) -or
    $resolvedEvidence.StartsWith($script:ResolvedProject + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Workflow evidence must be outside the production checkout.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this helper from an Administrator console.'
}
if ($PreviousCommit -eq $ExpectedCommit) { throw 'Previous and target commits must differ.' }
$script:Python = Join-Path $script:ResolvedProject 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $script:Python -PathType Leaf)) { throw 'Production virtual-environment Python was not found.' }
$script:ResolvedRisk = ''
$riskHash = ''
if ($InternalOnlyUnsignedRisk) {
    if ([string]::IsNullOrWhiteSpace($RiskAcceptance)) { throw 'Internal-only activation requires the approved risk acceptance file.' }
    $script:ResolvedRisk = (Resolve-Path -LiteralPath $RiskAcceptance -ErrorAction Stop).Path
    Assert-NoLinkedPath $script:ResolvedRisk
    $riskHash = Get-WorkflowSha256 $script:ResolvedRisk
} elseif ($RiskAcceptance) { throw 'Do not supply a risk exception in signed-production mode.' }

if ($Stage -ne 'Activate' -and [string]::IsNullOrWhiteSpace($WorkflowId)) {
    throw 'Verify/Finalize require the WorkflowId printed by Activate.'
}
if ($Stage -eq 'Activate' -and $WorkflowId) { throw 'Activate creates a new workflow; use Verify to resume checks.' }
if (-not $WorkflowId) {
    $WorkflowId = $ReleaseTag + '-' + [datetime]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
}
if ($WorkflowId -notmatch '^v\d+\.\d+\.\d+-\d{8}T\d{6}Z-[0-9a-f]{8}$' -or
    -not $WorkflowId.StartsWith($ReleaseTag + '-', [StringComparison]::Ordinal)) {
    throw 'Invalid WorkflowId.'
}

if (-not (Test-Path -LiteralPath $resolvedEvidence -PathType Container)) {
    New-Item -ItemType Directory -Path $resolvedEvidence | Out-Null
    Invoke-CheckedNative 'icacls.exe' @($resolvedEvidence, '/inheritance:r', '/grant:r',
        '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F')
}
Assert-ProtectedEvidenceRoot $resolvedEvidence
$lock = $null
$script:WorkflowState = $null
$script:MayWriteState = $false
$previousProjectOverride = [Environment]::GetEnvironmentVariable('MTO_PROJECT_ROOT', 'Process')
$env:MTO_PROJECT_ROOT = $script:ResolvedProject
Push-Location $script:ResolvedProject
try {
    Assert-NoLinkedPath (Join-Path $resolvedEvidence 'workflow.lock')
    $lock = [IO.File]::Open((Join-Path $resolvedEvidence 'workflow.lock'),
        [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $script:RunDirectory = Join-Path $resolvedEvidence $WorkflowId
    $script:GateDirectory = $script:RunDirectory
    $script:StatePath = Join-Path $script:RunDirectory 'workflow-state.json'
    Assert-NoLinkedPath $script:StatePath
    $manifestHash = Get-WorkflowSha256 (Join-Path $script:ResolvedDistribution 'release-manifest.json')
    if ($Stage -eq 'Activate') {
        Assert-Checkout $script:ResolvedProject $PreviousCommit
        Assert-ReleaseIdentity $ReleaseTag $ExpectedCommit $script:ResolvedDistribution
        Invoke-CheckedNative 'git' @('merge-base', '--is-ancestor', $PreviousCommit, $ExpectedCommit)
        if (Test-Path -LiteralPath $script:RunDirectory) { throw 'Workflow directory already exists; no evidence will be overwritten.' }
        $confirmation = Read-Host "Close client apps for this maintenance window. Type BEGIN MTO RELEASE $ReleaseTag"
        if ($confirmation -cne "BEGIN MTO RELEASE $ReleaseTag") { throw 'Maintenance-window approval not supplied.' }
        New-Item -ItemType Directory -Path $script:RunDirectory | Out-Null
        Invoke-CheckedNative 'icacls.exe' @($script:RunDirectory, '/inheritance:r', '/grant:r',
            '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F')
        $script:WorkflowState = [ordered]@{
            format_version = 1; release_tag = $ReleaseTag; expected_commit = $ExpectedCommit
            previous_commit = $PreviousCommit; project_root = $script:ResolvedProject
            distribution = $script:ResolvedDistribution; internal_only = [bool]$InternalOnlyUnsignedRisk
            risk_sha256 = $riskHash; manifest_sha256 = $manifestHash
            started_utc = [datetime]::UtcNow.ToString('o'); status = 'PREPARING'
            current_step = ''; activation_completed = $false; failure_stage = ''
            manual_accepted_utc = ''; completed_utc = ''; last_check_directory = ''
            baseline_sha256 = ''
        }
        $script:MayWriteState = $true
        Write-WorkflowState $script:WorkflowState $script:StatePath
        Invoke-Gate 'backup' @('-c',
            "import asyncio; from backend.services.backup_service import run_hybrid_backup; ok,msg=asyncio.run(run_hybrid_backup(user={'id':0,'username':'approved-release-workflow','role':'admin'})); print({'success':ok,'message':msg}); raise SystemExit(0 if ok else 2)")
        Invoke-Gate 'reliability-before' @('-m', 'scripts.phase4_reliability_preflight', '--require-ready',
            '--output', (Join-Path $script:RunDirectory 'reliability-before.json'))
        Invoke-AuditGate 'audit-before'
        Invoke-Gate 'financial-before' @('-m', 'scripts.phase6_financial_reconciliation_preflight', '--require-ready',
            '--output', (Join-Path $script:RunDirectory 'financial-before.json'))
        Invoke-Gate 'baseline-before' @('-m', 'scripts.capture_remediation_baseline', '--database', '--require-ready',
            '--output', (Join-Path $script:RunDirectory 'baseline-before.json'))
        $script:WorkflowState.baseline_sha256 = Get-WorkflowSha256 (Join-Path $script:RunDirectory 'baseline-before.json')
        Assert-Checkout $script:ResolvedProject $PreviousCommit
        $script:WorkflowState.status = 'ACTIVATING'
        $script:WorkflowState.current_step = 'immutable-updater'
        Write-WorkflowState $script:WorkflowState $script:StatePath
        $updaterArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            (Join-Path $script:ResolvedProject 'scripts\apply_immutable_release.ps1'), '-Apply',
            '-ReleaseTag', $ReleaseTag, '-Distribution', $script:ResolvedDistribution,
            '-ProjectRoot', $script:ResolvedProject)
        if ($InternalOnlyUnsignedRisk) {
            $updaterArguments += @('-InternalOnlyUnsignedRisk', '-RiskAcceptance', $script:ResolvedRisk)
        }
        # Interactive unsigned-release approval remains in the existing updater.
        Invoke-CheckedNative (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') $updaterArguments
        $script:WorkflowState.activation_completed = $true
        Write-WorkflowState $script:WorkflowState $script:StatePath
    } else {
        $script:WorkflowState = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
        Assert-ResumeState $script:WorkflowState $ReleaseTag $ExpectedCommit $PreviousCommit `
            $script:ResolvedProject $script:ResolvedDistribution ([bool]$InternalOnlyUnsignedRisk) $riskHash $manifestHash
        if (-not (Test-Path -LiteralPath (Join-Path $script:RunDirectory 'baseline-before.json') -PathType Leaf)) {
            throw 'Original baseline is missing. Do not recreate it after activation.'
        }
        Assert-NoLinkedPath (Join-Path $script:RunDirectory 'baseline-before.json')
        if ((Get-WorkflowSha256 (Join-Path $script:RunDirectory 'baseline-before.json')) -ne $script:WorkflowState.baseline_sha256) {
            throw 'Original baseline identity mismatch. No checks will resume.'
        }
        $script:MayWriteState = $true
    }
    $script:WorkflowState.status = 'VERIFYING'
    Write-WorkflowState $script:WorkflowState $script:StatePath
    Invoke-PostChecks
    $script:WorkflowState.status = 'READY_FOR_PILOT'
    Write-WorkflowState $script:WorkflowState $script:StatePath
    if ($Stage -eq 'Finalize') {
        $manualFlags = @(Read-ManualAcceptance $ReleaseTag)
        $script:WorkflowState.manual_accepted_utc = [datetime]::UtcNow.ToString('o')
        $finalPath = Join-Path $script:GateDirectory 'production-final.json'
        $finalArguments = @(Get-CertificationArguments $true $finalPath) + $manualFlags
        Invoke-Gate 'production-final' $finalArguments
        $final = Get-Content -LiteralPath $finalPath -Raw | ConvertFrom-Json
        if ($final.status -notin @('PASS', 'PASS_WITH_ACCEPTED_RISK')) { throw 'Final production certification did not pass.' }
        $script:WorkflowState.status = $final.status
        $script:WorkflowState.completed_utc = [datetime]::UtcNow.ToString('o')
        Assert-Checkout $script:ResolvedProject $ExpectedCommit
        Write-WorkflowState $script:WorkflowState $script:StatePath
    }
    Write-Host "MTO RELEASE WORKFLOW: $($script:WorkflowState.status)"
    Write-Host "Release: $ReleaseTag | Source: $($ExpectedCommit.Substring(0, 12))"
    Write-Host "WorkflowId: $WorkflowId"
    Write-Host "Evidence: $script:RunDirectory"
    if ($Stage -ne 'Finalize') { Write-Host 'Next: install the verified client, complete the pilot, then run Finalize for this WorkflowId.' }
} catch {
    if ($script:MayWriteState) {
        $script:WorkflowState.status = 'BLOCKED'
        $script:WorkflowState.failure_stage = $script:WorkflowState.current_step
        Write-WorkflowState $script:WorkflowState $script:StatePath
    }
    Write-Host "MTO RELEASE WORKFLOW: BLOCKED | WorkflowId: $WorkflowId"
    Write-Host 'No automatic cleanup or new rollback was performed by this helper. Review the failing gate and protected updater evidence.'
    throw
} finally {
    if ($lock) { $lock.Dispose() }
    Pop-Location
    [Environment]::SetEnvironmentVariable('MTO_PROJECT_ROOT', $previousProjectOverride, 'Process')
}
