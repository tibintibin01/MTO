$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$InnoScript = Join-Path $Root "installer\MTO_Treasury_Setup.iss"
$IsccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)

if (-not (Test-Path $Exe)) {
    $PyInstaller = Join-Path $Root "venv\Scripts\pyinstaller.exe"
    $Spec = Join-Path $Root "Treasury.spec"

    if (-not (Test-Path $PyInstaller)) {
        throw "PyInstaller was not found at $PyInstaller. Build Treasury.exe first or install PyInstaller in the project venv."
    }
    if (-not (Test-Path $Spec)) {
        throw "PyInstaller spec was not found at $Spec."
    }

    & $PyInstaller --clean --noconfirm $Spec
}

foreach ($required in @($Exe, (Join-Path $Dist ".env"), (Join-Path $Root "server_config.json"), $InnoScript)) {
    if (-not (Test-Path $required)) {
        throw "Required installer input is missing: $required"
    }
}

$Iscc = $IsccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) {
    throw "Inno Setup 6 compiler was not found. Install Inno Setup, then run this script again."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Dist "installer") | Out-Null
& $Iscc $InnoScript

$Installer = Join-Path $Dist "installer\MTO_Treasury_Setup.exe"
if (-not (Test-Path $Installer)) {
    throw "Installer build finished, but the expected output was not found: $Installer"
}

Write-Host "Installer created: $Installer"
