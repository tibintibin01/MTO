$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$BuildScript = Join-Path $Root "build_pyinstaller.ps1"
$InnoScript = Join-Path $Root "installer\MTO_Treasury_Setup.iss"
$DefaultConfig = Join-Path $Root "installer\default_config.json"
$IsccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

foreach ($required in @(
    $BuildScript,
    (Join-Path $Root "server_config.json"),
    $InnoScript,
    $DefaultConfig
)) {
    if (-not (Test-Path $required)) {
        throw "Required installer input is missing: $required"
    }
}

# Always rebuild so an older EXE that embedded server secrets cannot be packaged.
& $BuildScript
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $Exe)) {
    throw "The trust-boundary desktop build failed."
}

$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 compiler was not found. Install Inno Setup, then run this script again."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Dist "installer") | Out-Null
& $Iscc $InnoScript
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$Installer = Join-Path $Dist "installer\MTO_Treasury_Setup.exe"
if (-not (Test-Path $Installer)) {
    throw "Installer build finished, but the expected output was not found: $Installer"
}

Write-Host "Installer created: $Installer"
