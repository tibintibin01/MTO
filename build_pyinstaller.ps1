$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Spec = Join-Path $Root "Treasury.spec"
$Verifier = Join-Path $Root "scripts\verify_desktop_trust_boundary.py"
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$PyzManifest = Join-Path $Root "build\Treasury\PYZ-00.toc"

foreach ($required in @($Python, $Spec, $Verifier, (Join-Path $Root "server_config.json"))) {
    if (-not (Test-Path $required)) {
        throw "Required desktop build input is missing: $required"
    }
}

# Never allow legacy secrets or private keys to survive beside the desktop EXE.
if (Test-Path $Dist) {
    & $Python $Verifier --require-config --distribution $Dist
    if ($LASTEXITCODE -ne 0) {
        throw "Existing dist content violates the desktop trust boundary."
    }
} else {
    & $Python $Verifier --require-config
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop trust-boundary verification failed."
    }
}

& $Python -m PyInstaller --clean --noconfirm $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $Exe)) {
    throw "Build finished, but Treasury.exe was not found at $Exe."
}

& $Python $Verifier --require-config --distribution $Dist --pyz-manifest $PyzManifest
if ($LASTEXITCODE -ne 0) {
    throw "Built desktop distribution violates the trust boundary."
}

Write-Host "PyInstaller executable created: $Exe"
