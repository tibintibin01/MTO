param(
    [string]$ProjectRoot = "C:\MTO",
    [string]$TaskName = "MTO Treasury API",
    [int[]]$Ports = @(8001, 3000)
)

$ErrorActionPreference = "Stop"
$resolvedRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
$projectPattern = [regex]::Escape($resolvedRoot)

Write-Host "Stopping the MTO API recovery task and existing runtime processes..."

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

# Stop only Python and Node runtime processes whose command line points to
# this MTO installation. This catches supervised, manual, and orphaned starts.
$projectProcesses = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and
    $_.CommandLine -match $projectPattern -and
    $_.Name -match '^(pythonw?|node)\.exe$'
}

foreach ($process in $projectProcesses) {
    if ($process.ProcessId -eq $PID) {
        continue
    }
    Write-Host "Stopping $($process.Name) PID $($process.ProcessId)"
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

Start-Sleep -Seconds 2

# Ports 8001 and 3000 are reserved by this installation. Clean up any
# remaining listener so the replacement API/frontend cannot fail with EADDRINUSE.
foreach ($port in $Ports) {
    $listeners = Get-NetTCPConnection `
        -State Listen `
        -LocalPort $port `
        -ErrorAction SilentlyContinue

    foreach ($listener in $listeners) {
        if ($listener.OwningProcess -and $listener.OwningProcess -ne $PID) {
            Write-Host "Releasing MTO port $port from PID $($listener.OwningProcess)"
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
        }
    }
}

Start-Sleep -Seconds 2

$occupied = foreach ($port in $Ports) {
    Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
}
if ($occupied) {
    $details = $occupied | ForEach-Object {
        "port $($_.LocalPort) (PID $($_.OwningProcess))"
    }
    throw "MTO runtime ports remain occupied: $($details -join ', ')"
}

Write-Host "Existing MTO runtime stopped; ports 8001 and 3000 are available."
