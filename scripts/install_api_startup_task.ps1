$ErrorActionPreference = "Stop"

$TaskName = "MTO Treasury API"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$Supervisor = Join-Path $ProjectRoot "scripts\run_api_supervisor.py"
$EnvFile = Join-Path $ProjectRoot ".env"

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run install_server_autostart.bat as Administrator."
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Virtual-environment Python was not found at $Python."
}
if (-not (Test-Path -LiteralPath $Supervisor)) {
    throw "API supervisor was not found at $Supervisor."
}
if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Server configuration file was not found at $EnvFile."
}

$envLines = Get-Content -LiteralPath $EnvFile
$backupSetting = $envLines | Where-Object {
    $_ -match '^\s*MTO_BACKUP_DIR\s*=\s*.+$'
} | Select-Object -First 1

if (-not $backupSetting) {
    $backupDirectory = Join-Path $env:USERPROFILE "mto_backups"
    New-Item -ItemType Directory -Path $backupDirectory -Force | Out-Null

    $envContent = [IO.File]::ReadAllText($EnvFile)
    $settingLine = "MTO_BACKUP_DIR=$backupDirectory"
    if ($envContent -match '(?m)^\s*MTO_BACKUP_DIR\s*=.*$') {
        $backupSettingPattern = New-Object regex '(?m)^\s*MTO_BACKUP_DIR\s*=.*$'
        $envContent = $backupSettingPattern.Replace($envContent, $settingLine, 1)
    }
    else {
        if ($envContent.Length -gt 0 -and -not $envContent.EndsWith("`n")) {
            $envContent += [Environment]::NewLine
        }
        $envContent += $settingLine + [Environment]::NewLine
    }

    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($EnvFile, $envContent, $utf8WithoutBom)
    Write-Host "Configured a stable server backup directory: $backupDirectory"
}

$existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existingTask) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

# Retire launchers from the old manual-start setup so the scheduled supervisor
# can own port 8001 without leaving duplicate or orphaned Python processes.
$projectPattern = [regex]::Escape($ProjectRoot)
$oldApiProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -match '^pythonw?\.exe$' -and
    $_.CommandLine -match $projectPattern -and
    (
        $_.CommandLine -match 'run_api_supervisor\.py' -or
        $_.CommandLine -match 'backend\.main' -or
        $_.CommandLine -match 'backend[\\/]main\.py'
    )
}
foreach ($process in $oldApiProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2

$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument ('"{0}"' -f $Supervisor) `
    -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$taskPrincipal = New-ScheduledTaskPrincipal `
    -UserId "SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Keeps the MTO Treasury API online and restarts it after crashes or hangs." `
    -Action $action `
    -Trigger $trigger `
    -Principal $taskPrincipal `
    -Settings $settings `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8001/readyz" `
            -UseBasicParsing `
            -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            $ready = $true
            break
        }
    }
    catch {
        # The supervisor may still be starting MariaDB connections and routes.
    }
}
$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName

if (-not $ready) {
    throw "The recovery task was installed, but the API did not become ready. Check $ProjectRoot\logs\api_supervisor.log."
}

Write-Host "MTO API startup recovery installed successfully."
Write-Host "Task state: $($task.State)"
Write-Host "Last task result: $($info.LastTaskResult)"
Write-Host "API readiness: ONLINE"
Write-Host "Supervisor log: $ProjectRoot\logs\api_supervisor.log"
