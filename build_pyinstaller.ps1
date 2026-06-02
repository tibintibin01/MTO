$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PyInstaller = Join-Path $Root "venv\Scripts\pyinstaller.exe"
$Spec = Join-Path $Root "Treasury.spec"
$Exe = Join-Path $Root "dist\Treasury.exe"

if (-not (Test-Path $PyInstaller)) {
    throw "PyInstaller was not found at $PyInstaller."
}

if (-not (Test-Path $Spec)) {
    throw "PyInstaller spec was not found at $Spec."
}

& $PyInstaller --clean --noconfirm $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $Exe)) {
    throw "Build finished, but Treasury.exe was not found at $Exe."
}

Write-Host "PyInstaller executable created: $Exe"
