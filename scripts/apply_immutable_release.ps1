param(
    [switch]$Apply,
    [switch]$Rollback,
    [string]$ReleaseTag,
    [string]$Distribution,
    [string]$RollbackId,
    [string]$ProjectRoot = "C:\MTO",
    [string]$EvidenceRoot = "C:\ProgramData\MTO\updates",
    [string]$TaskName = "MTO Treasury API"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ReleasePattern = '^v\d+\.\d+\.\d+$'
$CommitPattern = '^[0-9a-f]{40}$'
$ApprovedOrigin = 'https://github.com/tibintibin01/mto'
$RequiredArtifacts = @(
    'Treasury.exe',
    'server_config.json',
    'certificates/mto-lan-ca.pem',
    'installer/MTO_Treasury_Setup.exe',
    'sbom.cdx.json'
)

function Invoke-NativeChecked {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FailureMessage (exit code $LASTEXITCODE)."
    }
}

function Get-GitText {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Git command failed: git $($Arguments -join ' ')"
    }
    return (($output | Out-String).Trim())
}

function Get-NormalizedOrigin {
    param([Parameter(Mandatory = $true)][string]$Value)
    $normalized = $Value.Trim().Replace('\', '/').TrimEnd('/').ToLowerInvariant()
    if ($normalized.EndsWith('.git')) {
        $normalized = $normalized.Substring(0, $normalized.Length - 4)
    }
    return $normalized
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run the immutable updater from an Administrator console.'
    }
}

function Assert-CleanApprovedCheckout {
    param([Parameter(Mandatory = $true)][string]$Root)
    $branch = Get-GitText @('branch', '--show-current')
    if ($branch -ne 'master') {
        throw 'The production checkout must be on master.'
    }
    $status = Get-GitText @('status', '--porcelain', '--untracked-files=all')
    if ($status) {
        throw 'The production checkout contains local changes. Review them before updating.'
    }
    $origin = Get-NormalizedOrigin (Get-GitText @('remote', 'get-url', 'origin'))
    if ($origin -ne $ApprovedOrigin) {
        throw 'The production checkout origin is not the approved MTO repository.'
    }
    $gitRoot = [IO.Path]::GetFullPath((Get-GitText @('rev-parse', '--show-toplevel'))).TrimEnd('\')
    if (-not $gitRoot.Equals($Root, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The updater is not running from the approved production checkout root.'
    }
}

function Get-ManifestProperties {
    param([Parameter(Mandatory = $true)]$Object)
    $values = @{}
    foreach ($property in $Object.PSObject.Properties) {
        $values[[string]$property.Name] = [string]$property.Value
    }
    return $values
}

function Assert-ReleasePackage {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$ExpectedTag,
        [Parameter(Mandatory = $true)][string]$ExpectedCommit
    )
    $manifestPath = Join-Path $PackageRoot 'release-manifest.json'
    $packageItem = Get-Item -LiteralPath $PackageRoot -Force
    if ($packageItem.Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'The release package root cannot be a linked or reparse-point directory.'
    }
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'The immutable release package is missing release-manifest.json.'
    }
    try {
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    } catch {
        throw 'The immutable release manifest is not valid JSON.'
    }
    if ([string]$manifest.version -ne $ExpectedTag) {
        throw 'The release manifest version does not match the approved tag.'
    }
    if ([string]$manifest.source_commit -ne $ExpectedCommit) {
        throw 'The release manifest source commit does not match the approved tag.'
    }
    if (-not $manifest.artifacts) {
        throw 'The release manifest does not contain artifact hashes.'
    }
    $hashes = Get-ManifestProperties $manifest.artifacts
    foreach ($relative in $RequiredArtifacts) {
        $artifact = [IO.Path]::GetFullPath((Join-Path $PackageRoot $relative))
        $prefix = $PackageRoot.TrimEnd('\') + '\'
        if (-not $artifact.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unsafe release artifact path: $relative"
        }
        if (-not (Test-Path -LiteralPath $artifact -PathType Leaf)) {
            throw "Required release artifact is missing: $relative"
        }
        if (-not $hashes.ContainsKey($relative)) {
            throw "Release manifest hash is missing: $relative"
        }
        $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $artifact).Hash.ToLowerInvariant()
        if ($actual -ne $hashes[$relative].ToLowerInvariant()) {
            throw "Release manifest hash mismatch: $relative"
        }
    }
    $linkedItems = @(Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force | Where-Object {
        $_.Attributes -band [IO.FileAttributes]::ReparsePoint
    })
    if ($linkedItems.Count -ne 0) {
        throw 'The release package contains a linked or reparse-point item.'
    }
    $privateItems = @(Get-ChildItem -LiteralPath $PackageRoot -File -Recurse -Force | Where-Object {
        $_.Extension.ToLowerInvariant() -in @('.key', '.p12', '.pfx') -or
        $_.Name.ToLowerInvariant().Contains('private_key') -or
        $_.Name.ToLowerInvariant().EndsWith('-key.pem') -or
        $_.Name.ToLowerInvariant().EndsWith('_key.pem')
    })
    if ($privateItems.Count -ne 0) {
        throw 'The release package contains forbidden private-key material.'
    }
    foreach ($relative in @('Treasury.exe', 'installer/MTO_Treasury_Setup.exe')) {
        $signature = Get-AuthenticodeSignature -LiteralPath (Join-Path $PackageRoot $relative)
        if ([string]$signature.Status -ne 'Valid') {
            throw "Authenticode signature is not valid for $relative."
        }
    }
    $sbom = Get-Content -LiteralPath (Join-Path $PackageRoot 'sbom.cdx.json') -Raw | ConvertFrom-Json
    if ([string]$sbom.bomFormat -ne 'CycloneDX' -or -not $sbom.specVersion -or -not $sbom.components) {
        throw 'The release package CycloneDX SBOM is missing or invalid.'
    }
}

function Write-State {
    param(
        [Parameter(Mandatory = $true)][hashtable]$State,
        [Parameter(Mandatory = $true)][string]$Path
    )
    $temporary = "$Path.tmp"
    $State.updated_at_utc = [DateTime]::UtcNow.ToString('o')
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Stop-MtoRuntime {
    param([Parameter(Mandatory = $true)][string]$Root)
    Invoke-NativeChecked 'powershell' @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $Root 'scripts\stop_mto_runtime.ps1'), '-ProjectRoot', $Root
    ) 'The MTO runtime could not be stopped safely'
}

function Start-MtoRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Python
    )
    & schtasks /Query /TN $TaskName *> $null
    if ($LASTEXITCODE -eq 0) {
        Invoke-NativeChecked 'schtasks' @('/Run', '/TN', $TaskName) 'The MTO API task could not be started'
    } else {
        Start-Process -FilePath $Python -ArgumentList @('-m', 'scripts.run_api_supervisor') -WorkingDirectory $Root -WindowStyle Hidden
    }
    Invoke-NativeChecked 'powershell' @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
        (Join-Path $Root 'scripts\wait_for_mto_api.ps1'), '-TimeoutSeconds', '90'
    ) 'The MTO API did not pass authenticated readiness'
}

function Install-LockedRuntime {
    param([Parameter(Mandatory = $true)][string]$Python)
    Invoke-NativeChecked $Python @(
        '-m', 'pip', 'install', '--require-hashes', '-r', 'requirements.lock', '-q'
    ) 'Hash-locked runtime dependency installation failed'
    Invoke-NativeChecked $Python @('-m', 'pip', 'check') 'Runtime dependency consistency check failed'
}

function New-LockedRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$BootstrapPython,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (Test-Path -LiteralPath $Destination) {
        throw 'The staged runtime destination already exists.'
    }
    Invoke-NativeChecked $BootstrapPython @('-m', 'venv', $Destination) 'The staged release runtime could not be created'
    $candidatePython = Join-Path $Destination 'Scripts\python.exe'
    Install-LockedRuntime $candidatePython
    return $candidatePython
}

function Switch-LockedRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$ActiveRuntime,
        [Parameter(Mandatory = $true)][string]$CandidateRuntime,
        [Parameter(Mandatory = $true)][string]$PreviousRuntime
    )
    if (-not (Test-Path -LiteralPath $ActiveRuntime -PathType Container)) {
        throw 'The active production runtime is missing.'
    }
    if (-not (Test-Path -LiteralPath $CandidateRuntime -PathType Container)) {
        throw 'The staged release runtime is missing.'
    }
    if (Test-Path -LiteralPath $PreviousRuntime) {
        throw 'The protected previous-runtime destination already exists.'
    }
    Move-Item -LiteralPath $ActiveRuntime -Destination $PreviousRuntime
    try {
        Move-Item -LiteralPath $CandidateRuntime -Destination $ActiveRuntime
    } catch {
        Move-Item -LiteralPath $PreviousRuntime -Destination $ActiveRuntime
        throw
    }
}

function Restore-LockedRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$ActiveRuntime,
        [Parameter(Mandatory = $true)][string]$PreviousRuntime,
        [Parameter(Mandatory = $true)][string]$FailedRuntime
    )
    if (-not (Test-Path -LiteralPath $PreviousRuntime -PathType Container)) {
        throw 'The protected previous runtime is unavailable.'
    }
    if (Test-Path -LiteralPath $FailedRuntime) {
        throw 'The failed-runtime evidence destination already exists.'
    }
    if (Test-Path -LiteralPath $ActiveRuntime -PathType Container) {
        Move-Item -LiteralPath $ActiveRuntime -Destination $FailedRuntime
    }
    try {
        Move-Item -LiteralPath $PreviousRuntime -Destination $ActiveRuntime
    } catch {
        if (Test-Path -LiteralPath $FailedRuntime -PathType Container) {
            Move-Item -LiteralPath $FailedRuntime -Destination $ActiveRuntime
        }
        throw
    }
}

function Invoke-ExplicitRollback {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Evidence,
        [Parameter(Mandatory = $true)][string]$Id
    )
    if ($Id -notmatch '^[A-Za-z0-9._-]+$') {
        throw 'Rollback ID contains invalid characters.'
    }
    $recordDirectory = [IO.Path]::GetFullPath((Join-Path $Evidence $Id))
    $evidencePrefix = $Evidence.TrimEnd('\') + '\'
    if (-not $recordDirectory.StartsWith($evidencePrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Unsafe rollback evidence path.'
    }
    $statePath = Join-Path $recordDirectory 'state.json'
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        throw 'The requested rollback evidence record does not exist.'
    }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    $rollbackCommit = [string]$state.previous_commit
    $targetCommit = [string]$state.target_commit
    $previousRuntime = [string]$state.previous_runtime
    if ($rollbackCommit -notmatch $CommitPattern) {
        throw 'The rollback evidence contains an invalid previous commit.'
    }
    if ($targetCommit -notmatch $CommitPattern) {
        throw 'The rollback evidence contains an invalid target commit.'
    }
    $previousRuntime = [IO.Path]::GetFullPath($previousRuntime)
    $recordPrefix = $recordDirectory.TrimEnd('\') + '\'
    if (-not $previousRuntime.StartsWith($recordPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'The rollback evidence contains an unsafe previous-runtime path.'
    }
    if (-not (Test-Path -LiteralPath $previousRuntime -PathType Container)) {
        throw 'The rollback evidence no longer contains the protected previous runtime.'
    }
    if (-not [bool]$state.runtime_switched) {
        throw 'The rollback record does not contain a completed runtime switch.'
    }
    Assert-CleanApprovedCheckout $Root
    $currentCommit = (Get-GitText @('rev-parse', 'HEAD')).ToLowerInvariant()
    if ($currentCommit -ne $targetCommit) {
        throw 'The active source no longer matches this rollback record.'
    }
    Invoke-NativeChecked 'git' @('cat-file', '-e', "$rollbackCommit`^{commit}") 'The rollback commit is unavailable'
    $confirmation = Read-Host "Type ROLLBACK IMMUTABLE MTO RELEASE $Id to continue"
    if ($confirmation -cne "ROLLBACK IMMUTABLE MTO RELEASE $Id") {
        throw 'Rollback confirmation did not match.'
    }
    New-Item -ItemType Directory -Path $Evidence -Force | Out-Null
    $lockPath = Join-Path $Evidence 'immutable-update.lock'
    $lock = $null
    try {
        $lock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    } catch {
        throw 'Another immutable update or rollback is already running.'
    }
    $activeRuntime = Join-Path $Root 'venv'
    $failedRuntime = Join-Path $recordDirectory "failed-venv-$([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))"
    $python = Join-Path $activeRuntime 'Scripts\python.exe'
    $rollbackBefore = Join-Path $recordDirectory 'rollback-financial-before.json'
    $rollbackAfter = Join-Path $recordDirectory 'rollback-financial-after.json'
    $rollbackMutationStarted = $false
    try {
        Invoke-NativeChecked $python @(
            '-m', 'scripts.capture_remediation_baseline', '--database', '--require-ready',
            '--output', $rollbackBefore
        ) 'The rollback financial baseline failed'
        $rollbackMutationStarted = $true
        Stop-MtoRuntime $Root
        Invoke-NativeChecked 'git' @('update-ref', "refs/mto/failed/$Id", $currentCommit) 'The failed-release reference could not be retained'
        Invoke-NativeChecked 'git' @('reset', '--hard', $rollbackCommit) 'The code rollback failed'
        Restore-LockedRuntime $activeRuntime $previousRuntime $failedRuntime
        $python = Join-Path $activeRuntime 'Scripts\python.exe'
        Invoke-NativeChecked $python @('-m', 'pip', 'check') 'The restored runtime dependency check failed'
        Start-MtoRuntime $Root $python
        Invoke-NativeChecked $python @(
            '-m', 'scripts.capture_remediation_baseline', '--database', '--require-ready',
            '--compare-to', $rollbackBefore, '--output', $rollbackAfter
        ) 'Financial invariants changed during rollback'
        $stateHash = @{}
        foreach ($property in $state.PSObject.Properties) {
            $stateHash[$property.Name] = $property.Value
        }
        $stateHash.rollback_status = 'COMPLETED'
        $stateHash.rollback_commit = $rollbackCommit
        $stateHash.rollback_completed_at_utc = [DateTime]::UtcNow.ToString('o')
        Write-State $stateHash $statePath
        Write-Host 'IMMUTABLE RELEASE CODE ROLLBACK: PASS'
        Write-Host "- Restored commit: $($rollbackCommit.Substring(0, 12))"
        Write-Host '- Database schema was not reversed.'
    } catch {
        $stateHash = @{}
        foreach ($property in $state.PSObject.Properties) {
            $stateHash[$property.Name] = $property.Value
        }
        $stateHash.rollback_status = 'FAILED'
        $stateHash.rollback_failure_type = $_.Exception.GetType().Name
        Write-State $stateHash $statePath
        if ($rollbackMutationStarted) {
            try {
                Stop-MtoRuntime $Root
            } catch {
                Write-Warning 'The failed rollback runtime could not be stopped cleanly.'
            }
        }
        throw
    } finally {
        if ($lock) {
            $lock.Dispose()
        }
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}

if ($Apply -eq $Rollback) {
    throw 'Specify exactly one of -Apply or -Rollback.'
}
Assert-Administrator

$resolvedProject = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$resolvedEvidence = [IO.Path]::GetFullPath($EvidenceRoot).TrimEnd('\')
if ($resolvedEvidence.StartsWith($resolvedProject + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Update evidence must be stored outside the active source checkout.'
}
Set-Location -LiteralPath $resolvedProject

if ($Rollback) {
    Invoke-ExplicitRollback $resolvedProject $resolvedEvidence $RollbackId
    exit 0
}

if ($ReleaseTag -notmatch $ReleasePattern) {
    throw 'ReleaseTag must use the stable semantic form vX.Y.Z.'
}
if (-not $Distribution) {
    throw 'Distribution is required for immutable release activation.'
}
$resolvedDistribution = [IO.Path]::GetFullPath($Distribution).TrimEnd('\')
if (-not (Test-Path -LiteralPath $resolvedDistribution -PathType Container)) {
    throw 'The immutable release distribution directory does not exist.'
}
if ($resolvedDistribution.StartsWith($resolvedProject + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The immutable release distribution must be staged outside the active checkout.'
}
Assert-CleanApprovedCheckout $resolvedProject

Invoke-NativeChecked 'git' @(
    '-c', 'gc.auto=0', '-c', 'maintenance.auto=false', 'fetch', '--no-tags', 'origin',
    'refs/heads/master:refs/remotes/origin/master',
    "refs/tags/$ReleaseTag`:refs/tags/$ReleaseTag"
) 'The approved branch and release tag could not be fetched'

$targetCommit = (Get-GitText @('rev-parse', "refs/tags/$ReleaseTag`^{commit}")).ToLowerInvariant()
$remoteCommit = (Get-GitText @('rev-parse', 'refs/remotes/origin/master')).ToLowerInvariant()
$previousCommit = (Get-GitText @('rev-parse', 'HEAD')).ToLowerInvariant()
if ($targetCommit -notmatch $CommitPattern -or $targetCommit -ne $remoteCommit) {
    throw 'The selected release tag does not identify the approved origin/master commit.'
}
if ($previousCommit -eq $targetCommit) {
    throw 'The selected immutable release is already active.'
}
& git merge-base --is-ancestor $previousCommit $targetCommit
if ($LASTEXITCODE -ne 0) {
    throw 'The selected release is not a fast-forward descendant of the active source.'
}
Assert-ReleasePackage $resolvedDistribution $ReleaseTag $targetCommit

$confirmation = Read-Host "Type APPLY IMMUTABLE MTO RELEASE $ReleaseTag to continue"
if ($confirmation -cne "APPLY IMMUTABLE MTO RELEASE $ReleaseTag") {
    throw 'Immutable release confirmation did not match.'
}

New-Item -ItemType Directory -Path $resolvedEvidence -Force | Out-Null
$lockPath = Join-Path $resolvedEvidence 'immutable-update.lock'
$lock = $null
try {
    $lock = [IO.File]::Open($lockPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
} catch {
    throw 'Another immutable update or rollback is already running.'
}

$recordId = "$ReleaseTag-$([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))"
$recordDirectory = Join-Path $resolvedEvidence $recordId
New-Item -ItemType Directory -Path $recordDirectory | Out-Null
$statePath = Join-Path $recordDirectory 'state.json'
$beforeBaseline = Join-Path $recordDirectory 'financial-before.json'
$afterBaseline = Join-Path $recordDirectory 'financial-after.json'
$supplyReport = Join-Path $recordDirectory 'supply-chain.json'
$auditReport = Join-Path $recordDirectory 'audit-integrity.json'
$rollbackRef = "refs/mto/rollback/$recordId"
$activeRuntime = Join-Path $resolvedProject 'venv'
$candidateRuntime = Join-Path $recordDirectory 'candidate-venv'
$previousRuntime = Join-Path $recordDirectory 'previous-venv'
$failedRuntime = Join-Path $recordDirectory 'failed-venv'
$python = Join-Path $activeRuntime 'Scripts\python.exe'
$state = @{
    format_version = 1
    record_id = $recordId
    release_tag = $ReleaseTag
    target_commit = $targetCommit
    previous_commit = $previousCommit
    distribution = $resolvedDistribution
    rollback_ref = $rollbackRef
    previous_runtime = $previousRuntime
    status = 'PREPARING'
    runtime_stop_attempted = $false
    runtime_stopped = $false
    source_switched = $false
    runtime_switched = $false
    migration_started = $false
    migration_completed = $false
}

try {
    Write-State $state $statePath
    Copy-Item -LiteralPath (Join-Path $resolvedDistribution 'release-manifest.json') -Destination (Join-Path $recordDirectory 'release-manifest.json')
    Invoke-NativeChecked $python @(
        '-m', 'scripts.capture_remediation_baseline', '--database', '--require-ready',
        '--output', $beforeBaseline
    ) 'The pre-update financial and backup baseline failed'
    Invoke-NativeChecked 'git' @('update-ref', $rollbackRef, $previousCommit) 'The rollback reference could not be created'
    Invoke-NativeChecked 'git' @('cat-file', '-e', "$rollbackRef`^{commit}") 'The rollback reference could not be verified'

    $state.status = 'STOPPING_RUNTIME'
    $state.runtime_stop_attempted = $true
    Write-State $state $statePath
    Stop-MtoRuntime $resolvedProject
    $state.runtime_stopped = $true
    Write-State $state $statePath

    Invoke-NativeChecked 'git' @('merge', '--ff-only', $targetCommit) 'The immutable source switch failed'
    $state.source_switched = $true
    $state.status = 'VERIFYING_RELEASE'
    Write-State $state $statePath

    Invoke-NativeChecked $python @(
        '-m', 'scripts.phase5_supply_chain_preflight', '--require-ready',
        '--distribution', $resolvedDistribution, '--output', $supplyReport
    ) 'The Phase 5 supply-chain gate rejected the selected release'
    [void](New-LockedRuntime $python $candidateRuntime)
    Switch-LockedRuntime $activeRuntime $candidateRuntime $previousRuntime
    $state.runtime_switched = $true
    $python = Join-Path $activeRuntime 'Scripts\python.exe'
    Invoke-NativeChecked $python @('-m', 'pip', 'check') 'The relocated release runtime dependency check failed'
    $state.status = 'RUNTIME_SWITCHED'
    Write-State $state $statePath

    $state.migration_started = $true
    $state.status = 'APPLYING_MIGRATIONS'
    Write-State $state $statePath
    Invoke-NativeChecked $python @('-m', 'migration_manager') 'Database migration failed'
    $state.migration_completed = $true
    $state.status = 'STARTING_RUNTIME'
    Write-State $state $statePath

    Start-MtoRuntime $resolvedProject $python
    $state.runtime_stopped = $false
    Write-State $state $statePath
    Invoke-NativeChecked $python @(
        '-m', 'scripts.phase5_audit_observability_preflight', '--require-ready',
        '--require-active', '--require-live-event', '--output', $auditReport
    ) 'Post-update audit integrity verification failed'
    Invoke-NativeChecked $python @(
        '-m', 'scripts.capture_remediation_baseline', '--database', '--require-ready',
        '--compare-to', $beforeBaseline, '--output', $afterBaseline
    ) 'Post-update financial invariants changed'

    $state.status = 'COMPLETED'
    $state.completed_at_utc = [DateTime]::UtcNow.ToString('o')
    Write-State $state $statePath
    Write-Host 'IMMUTABLE MTO RELEASE UPDATE: PASS'
    Write-Host "- Release: $ReleaseTag"
    Write-Host "- Source: $($targetCommit.Substring(0, 12))"
    Write-Host "- Rollback ID: $recordId"
    Write-Host "- Protected evidence: $recordDirectory"
} catch {
    $state.status = 'FAILED'
    $state.failure_stage = if ($state.migration_started) { 'MIGRATION_OR_LATER' } elseif ($state.source_switched) { 'SOURCE_SWITCHED_PRE_MIGRATION' } else { 'PRE_SWITCH' }
    $state.failure_type = $_.Exception.GetType().Name
    Write-State $state $statePath
    if ($state.source_switched -and -not $state.migration_started) {
        Write-Warning 'Activation failed before migrations. Restoring the retained code revision.'
        try {
            Invoke-NativeChecked 'git' @('reset', '--hard', $previousCommit) 'Automatic pre-migration code rollback failed'
            if ($state.runtime_switched) {
                Restore-LockedRuntime $activeRuntime $previousRuntime $failedRuntime
                $python = Join-Path $activeRuntime 'Scripts\python.exe'
            }
            Invoke-NativeChecked $python @('-m', 'pip', 'check') 'The restored runtime dependency check failed'
            Start-MtoRuntime $resolvedProject $python
            $state.runtime_stopped = $false
            $state.status = 'ROLLED_BACK_PRE_MIGRATION'
            Write-State $state $statePath
        } catch {
            Write-Warning 'Automatic pre-migration rollback did not complete. Keep the API stopped and review the protected evidence.'
        }
    } elseif ($state.runtime_stop_attempted -and -not $state.source_switched) {
        Write-Warning 'Activation stopped before the source switch. Restarting the unchanged runtime.'
        try {
            Start-MtoRuntime $resolvedProject $python
            $state.runtime_stopped = $false
            $state.status = 'ABORTED_PRE_SWITCH_RUNTIME_RESTORED'
            Write-State $state $statePath
        } catch {
            Write-Warning 'The unchanged runtime could not be restarted. Review the protected evidence.'
        }
    } elseif ($state.migration_started) {
        try {
            Stop-MtoRuntime $resolvedProject
            $state.runtime_stopped = $true
            Write-State $state $statePath
        } catch {
            Write-Warning 'The failed post-migration runtime could not be stopped cleanly.'
        }
        Write-Warning "Database migration began. Keep the evidence and request an explicit rollback review using ID $recordId."
    }
    throw
} finally {
    if ($lock) {
        $lock.Dispose()
    }
    Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
}
