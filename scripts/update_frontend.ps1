param(
    [string]$ProjectRoot = "C:\MTO",
    [int]$InstallTimeoutMinutes = 20,
    [int]$BuildTimeoutMinutes = 30
)

$ErrorActionPreference = "Stop"
$Frontend = Join-Path $ProjectRoot "frontend"
$Logs = Join-Path $ProjectRoot "logs"
$BuildStamp = Join-Path $Frontend ".mto-built-tree"
$DependencyStamp = Join-Path $Frontend "node_modules\.mto-package-inputs.sha256"
$StagedBuild = Join-Path $Frontend ".next-update"
$LiveBuild = Join-Path $Frontend ".next"
$PreviousBuild = Join-Path $Frontend ".next-previous"

New-Item -ItemType Directory -Force -Path $Logs | Out-Null

function Invoke-LoggedProcess {
    param(
        [string]$Name,
        [string[]]$Arguments,
        [int]$TimeoutMinutes,
        [string]$LogPrefix
    )

    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    $stdout = Join-Path $Logs "$LogPrefix.out.log"
    $stderr = Join-Path $Logs "$LogPrefix.err.log"
    Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue

    $process = Start-Process -FilePath $npm `
        -ArgumentList $Arguments `
        -WorkingDirectory $Frontend `
        -NoNewWindow `
        -PassThru `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr

    $started = Get-Date
    $lastLine = ""
    while (-not $process.HasExited) {
        Start-Sleep -Seconds 3
        $elapsed = (Get-Date) - $started
        if ($elapsed.TotalMinutes -ge $TimeoutMinutes) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            Write-Host ""
            Write-Host "ERROR: $Name exceeded $TimeoutMinutes minutes and was stopped." -ForegroundColor Red
            Write-Host "Logs: $stdout and $stderr"
            return 124
        }

        $currentLine = Get-Content -LiteralPath $stdout -Tail 1 -ErrorAction SilentlyContinue
        if ($currentLine -and $currentLine -ne $lastLine) {
            Write-Host "  $currentLine"
            $lastLine = $currentLine
        } elseif ([int]$elapsed.TotalSeconds % 15 -lt 3) {
            Write-Host ("  {0} still running ({1:mm\:ss})..." -f $Name, $elapsed)
        }
    }

    $process.WaitForExit()
    Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host $_ }
    Get-Content -LiteralPath $stderr -ErrorAction SilentlyContinue |
        ForEach-Object { Write-Host $_ }
    return $process.ExitCode
}

if (-not (Test-Path (Join-Path $Frontend "package.json"))) {
    Write-Host "ERROR: Frontend package.json was not found at $Frontend." -ForegroundColor Red
    exit 1
}

$frontendTree = (& git -C $ProjectRoot rev-parse "HEAD:frontend").Trim()
if ($LASTEXITCODE -ne 0 -or -not $frontendTree) {
    Write-Host "ERROR: Could not determine the committed frontend version." -ForegroundColor Red
    exit 1
}

$builtTree = if (Test-Path $BuildStamp) {
    (Get-Content -LiteralPath $BuildStamp -Raw).Trim()
} else {
    ""
}

if ($builtTree -eq $frontendTree -and (Test-Path (Join-Path $LiveBuild "BUILD_ID"))) {
    Write-Host "Frontend source is unchanged; using the existing verified build."
    exit 0
}

$packageInputs = @(
    (Get-FileHash -Algorithm SHA256 (Join-Path $Frontend "package.json")).Hash,
    (Get-FileHash -Algorithm SHA256 (Join-Path $Frontend "package-lock.json")).Hash
) -join ":"
$installedInputs = if (Test-Path $DependencyStamp) {
    (Get-Content -LiteralPath $DependencyStamp -Raw).Trim()
} else {
    ""
}

if (-not (Test-Path (Join-Path $Frontend "node_modules")) -or $installedInputs -ne $packageInputs) {
    Write-Host "Installing frontend dependencies. Progress is recorded in C:\MTO\logs..."
    $installCode = Invoke-LoggedProcess `
        -Name "Frontend dependency installation" `
        -Arguments @("ci", "--no-audit", "--no-fund", "--prefer-offline") `
        -TimeoutMinutes $InstallTimeoutMinutes `
        -LogPrefix "frontend_npm_ci"
    if ($installCode -ne 0) {
        exit $installCode
    }
    Set-Content -LiteralPath $DependencyStamp -Value $packageInputs -Encoding ASCII
} else {
    Write-Host "Frontend dependencies are unchanged; skipping npm ci."
}

foreach ($target in @($StagedBuild, $PreviousBuild)) {
    if (Test-Path $target) {
        Remove-Item -LiteralPath $target -Recurse -Force
    }
}

$previousNodeOptions = $env:NODE_OPTIONS
$previousDistDir = $env:MTO_NEXT_DIST_DIR
$previousTelemetry = $env:NEXT_TELEMETRY_DISABLED
try {
    $env:NODE_OPTIONS = "--max-old-space-size=1536"
    $env:MTO_NEXT_DIST_DIR = ".next-update"
    $env:NEXT_TELEMETRY_DISABLED = "1"

    Write-Host "Building the updated frontend safely. This can take several minutes."
    $buildCode = Invoke-LoggedProcess `
        -Name "Frontend production build" `
        -Arguments @("run", "build") `
        -TimeoutMinutes $BuildTimeoutMinutes `
        -LogPrefix "frontend_build"
    if ($buildCode -ne 0) {
        exit $buildCode
    }
} finally {
    $env:NODE_OPTIONS = $previousNodeOptions
    $env:MTO_NEXT_DIST_DIR = $previousDistDir
    $env:NEXT_TELEMETRY_DISABLED = $previousTelemetry
}

if (-not (Test-Path (Join-Path $StagedBuild "BUILD_ID"))) {
    Write-Host "ERROR: Build completed without a staged BUILD_ID." -ForegroundColor Red
    exit 1
}

if (Test-Path $LiveBuild) {
    Move-Item -LiteralPath $LiveBuild -Destination $PreviousBuild
}
try {
    Move-Item -LiteralPath $StagedBuild -Destination $LiveBuild
    Set-Content -LiteralPath $BuildStamp -Value $frontendTree -Encoding ASCII
    if (Test-Path $PreviousBuild) {
        Remove-Item -LiteralPath $PreviousBuild -Recurse -Force
    }
} catch {
    if (-not (Test-Path $LiveBuild) -and (Test-Path $PreviousBuild)) {
        Move-Item -LiteralPath $PreviousBuild -Destination $LiveBuild
    }
    throw
}

Write-Host "Frontend build verified and activated."
