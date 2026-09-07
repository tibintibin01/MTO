$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root "venv\Scripts\python.exe"
$Spec = Join-Path $Root "Treasury.spec"
$Verifier = Join-Path $Root "scripts\verify_desktop_trust_boundary.py"
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$PyzManifest = Join-Path $Root "build\Treasury\PYZ-00.toc"
$Config = Join-Path $Root "server_config.json"
$PublicCa = Join-Path $Root "certificates\mto-lan-ca.pem"

foreach ($required in @($Python, $Spec, $Verifier, $Config, $PublicCa)) {
    if (-not (Test-Path $required)) {
        throw "Required desktop build input is missing: $required"
    }
}

& $Python $Verifier --require-config
if ($LASTEXITCODE -ne 0) {
    throw "Desktop trust-boundary verification failed."
}

& $Python -m PyInstaller --clean --noconfirm $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path $Exe)) {
    throw "Build finished, but Treasury.exe was not found at $Exe."
}
$configData = Get-Content -LiteralPath $Config -Raw | ConvertFrom-Json
if ([string]$configData.server_url -notmatch '^https://') {
    throw "server_config.json must use an HTTPS server_url."
}
if ([string]$configData.ca_certificate -ne 'certificates/mto-lan-ca.pem') {
    throw "server_config.json ca_certificate must be certificates/mto-lan-ca.pem."
}

# The endpoint config and public CA remain external to Treasury.exe so a CA or
# server-address rotation does not require rebuilding application code.
$distCertificates = Join-Path $Dist "certificates"
New-Item -ItemType Directory -Force -Path $distCertificates | Out-Null
Copy-Item -LiteralPath $Config -Destination (Join-Path $Dist "server_config.json") -Force
Copy-Item -LiteralPath $PublicCa -Destination (Join-Path $distCertificates "mto-lan-ca.pem") -Force

$privateMaterial = Get-ChildItem -LiteralPath $Dist -Recurse -File | Where-Object {
    $_.Name -match '(?i)(^|[-_])(private|server|ca)[-_]?key\.(pem|key)$' -or
    $_.Extension -in @('.pfx', '.p12')
}
if ($privateMaterial) {
    throw "Private TLS material was found in the desktop distribution."
}


& $Python $Verifier --require-config --distribution $Dist --pyz-manifest $PyzManifest
if ($LASTEXITCODE -ne 0) {
    throw "Built desktop distribution violates the trust boundary."
}

Write-Host "PyInstaller executable created: $Exe"
