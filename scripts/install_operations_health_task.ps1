[CmdletBinding(DefaultParameterSetName = "Preflight")]
param(
    [Parameter(ParameterSetName = "Preflight")]
    [switch]$Preflight,

    [Parameter(Mandatory = $true, ParameterSetName = "Apply")]
    [switch]$Apply,

    [ValidatePattern('^(?:[01]\d|2[0-3]):[0-5]\d$')]
    [string]$DailyAt = "06:30",

    [ValidateRange(30, 3650)]
    [int]$RetentionDays = 400
)

$ErrorActionPreference = "Stop"
$TaskName = "MTO Operations Health Check"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$Runner = Join-Path $ProjectRoot "scripts\run_operations_health_check.py"
$WorkingDirectory = [IO.Path]::GetFullPath($ProjectRoot)
$Arguments = "-m scripts.run_operations_health_check --retention-days $RetentionDays"
$ScheduleTime = [datetime]::ParseExact(
    $DailyAt,
    "HH:mm",
    [Globalization.CultureInfo]::InvariantCulture
)

function Test-ApprovedTaskConfiguration {
    param(
        [Parameter(Mandatory = $true)]
        $Task
    )

    try {
        $taskAction = $Task.Actions | Select-Object -First 1
        $taskTrigger = $Task.Triggers | Select-Object -First 1
        $actualPython = [IO.Path]::GetFullPath([string]$taskAction.Execute)
        $actualWorkingDirectory = [IO.Path]::GetFullPath(
            [string]$taskAction.WorkingDirectory
        )
        $triggerClass = [string]$taskTrigger.CimClass.CimClassName
        $triggerTime = ([datetime]$taskTrigger.StartBoundary).TimeOfDay
        $executionLimit = [Xml.XmlConvert]::ToTimeSpan(
            [string]$Task.Settings.ExecutionTimeLimit
        )

        return (
            $actualPython -eq [IO.Path]::GetFullPath($Python) -and
            [string]$taskAction.Arguments -eq $Arguments -and
            $actualWorkingDirectory -eq $WorkingDirectory -and
            [string]$Task.Principal.UserId -in @("SYSTEM", "NT AUTHORITY\SYSTEM") -and
            [string]$Task.Principal.LogonType -eq "ServiceAccount" -and
            [string]$Task.Principal.RunLevel -eq "Highest" -and
            $triggerClass -eq "MSFT_TaskDailyTrigger" -and
            $triggerTime -eq $ScheduleTime.TimeOfDay -and
            [string]$Task.Settings.MultipleInstances -eq "IgnoreNew" -and
            [bool]$Task.Settings.StartWhenAvailable -and
            $executionLimit -eq (New-TimeSpan -Minutes 30)
        )
    }
    catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "The managed MTO virtual-environment Python executable was not found."
}
if (-not (Test-Path -LiteralPath $Runner -PathType Leaf)) {
    throw "The operations health runner was not found."
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdministrator = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($existingTask) {
    if (-not (Test-ApprovedTaskConfiguration -Task $existingTask)) {
        throw "An existing operations task does not match the approved configuration."
    }
}

if (-not $Apply) {
    Write-Host "OPERATIONS WORKSTREAM 2 SCHEDULER PREFLIGHT: PASS"
    Write-Host ""
    Write-Host "- Task name: $TaskName"
    Write-Host "- Daily local-server time: $DailyAt"
    Write-Host "- Report retention: $RetentionDays days"
    Write-Host "- Run as SYSTEM: YES"
    Write-Host "- Overlapping runs: BLOCKED"
    Write-Host "- Execution limit: 30 minutes"
    Write-Host "- Existing approved task: $(if ($existingTask) { 'YES' } else { 'NO' })"
    Write-Host "- Administrator context: $(if ($isAdministrator) { 'YES' } else { 'NO' })"
    Write-Host "  No task, report, configuration, service, or database was changed."
    exit 0
}

if (-not $isAdministrator) {
    throw "Run the scheduler activation from an Administrator PowerShell session."
}

Write-Host "This operation registers the read-only MTO operations health task."
Write-Host "It does not restart services, repair data, or create backups."
$confirmation = Read-Host "Type INSTALL MTO OPERATIONS HEALTH TASK to continue"
if ($confirmation -cne "INSTALL MTO OPERATIONS HEALTH TASK") {
    throw "Scheduler activation cancelled because the confirmation phrase did not match."
}

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $Arguments `
    -WorkingDirectory $WorkingDirectory
$trigger = New-ScheduledTaskTrigger -Daily -At $ScheduleTime
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Runs the privacy-safe, read-only MTO operational assurance checks." `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Force | Out-Null

$installedTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
if (-not (Test-ApprovedTaskConfiguration -Task $installedTask)) {
    throw "The registered operations task failed post-installation verification."
}

Write-Host "OPERATIONS WORKSTREAM 2 SCHEDULER ACTIVATION: PASS"
Write-Host ""
Write-Host "- Task name: $TaskName"
Write-Host "- Daily local-server time: $DailyAt"
Write-Host "- Report retention: $RetentionDays days"
Write-Host "- Task state: $($installedTask.State)"
Write-Host "- Immediate execution: NOT STARTED"
Write-Host "  Run the separately approved post-activation smoke test next."
