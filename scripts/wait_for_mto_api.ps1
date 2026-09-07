param(
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 90,
    [string]$HealthUrl = "",
    [string]$CaCertificate = ""
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Virtual-environment Python was not found at $python."
}

$arguments = @(
    "-m",
    "scripts.check_api_readiness",
    "--timeout-seconds",
    $TimeoutSeconds.ToString()
)
if (-not [string]::IsNullOrWhiteSpace($HealthUrl)) {
    $arguments += @("--health-url", $HealthUrl)
}
if (-not [string]::IsNullOrWhiteSpace($CaCertificate)) {
    $arguments += @("--ca-certificate", $CaCertificate)
}

Push-Location $projectRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
