param(
    [string]$PythonPath = "",
    [string]$SigningCertificateThumbprint = $env:MTO_CODE_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampUrl = "https://timestamp.digicert.com",
    [switch]$AllowUnsignedDevelopmentBuild
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $Python = Join-Path $Root ".phase5-release-venv\Scripts\python.exe"
} else {
    $Python = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
}

$Spec = Join-Path $Root "Treasury.spec"
$Verifier = Join-Path $Root "scripts\verify_desktop_trust_boundary.py"
$ReleaseMetadata = Join-Path $Root "scripts\build_release_metadata.py"
$DevRequirements = Join-Path $Root "dev-requirements.txt"
$DevRequirementsLock = Join-Path $Root "dev-requirements.lock"
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$PyzManifest = Join-Path $Root "build\Treasury\PYZ-00.toc"
$Config = Join-Path $Root "server_config.json"
$PublicCa = Join-Path $Root "certificates\mto-lan-ca.pem"

foreach ($required in @(
    $Python,
    $Spec,
    $Verifier,
    $ReleaseMetadata,
    $DevRequirements,
    $DevRequirementsLock,
    $Config,
    $PublicCa
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required desktop build input is missing: $required"
    }
}

& $Python -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 2)"
if ($LASTEXITCODE -ne 0) {
    throw "The immutable desktop release must use the approved Python 3.11 build runtime."
}

function Resolve-SignToolPath {
    $command = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    $kitsRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (Test-Path -LiteralPath $kitsRoot -PathType Container) {
        $candidate = Get-ChildItem -LiteralPath $kitsRoot -Filter "signtool.exe" -File -Recurse |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }
    throw "Windows SDK signtool.exe was not found."
}

function Assert-ValidAuthenticodeSignature {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$ExpectedThumbprint
    )
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ([string]$signature.Status -ne "Valid" -or -not $signature.SignerCertificate) {
        throw "Authenticode signature validation failed for $([IO.Path]::GetFileName($Path))."
    }
    $actual = ([string]$signature.SignerCertificate.Thumbprint).Replace(" ", "").ToUpperInvariant()
    $expected = $ExpectedThumbprint.Replace(" ", "").ToUpperInvariant()
    if ($actual -ne $expected) {
        throw "Authenticode signer mismatch for $([IO.Path]::GetFileName($Path))."
    }
}

function Invoke-CodeSigning {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Thumbprint
    )
    $normalized = $Thumbprint.Replace(" ", "").ToUpperInvariant()
    if ($normalized -notmatch '^[0-9A-F]{40,64}$') {
        throw "The code-signing certificate thumbprint format is invalid."
    }
    if ($TimestampUrl -notmatch '^https://') {
        throw "The code-signing timestamp URL must use HTTPS."
    }
    $signTool = Resolve-SignToolPath
    & $signTool sign /sha1 $normalized /fd SHA256 /td SHA256 /tr $TimestampUrl $Path
    if ($LASTEXITCODE -ne 0) {
        throw "Authenticode signing failed for $([IO.Path]::GetFileName($Path))."
    }
    Assert-ValidAuthenticodeSignature -Path $Path -ExpectedThumbprint $normalized
}

if ([string]::IsNullOrWhiteSpace($SigningCertificateThumbprint) -and
    -not $AllowUnsignedDevelopmentBuild) {
    throw "A managed code-signing certificate is required. Use -AllowUnsignedDevelopmentBuild only for non-production validation."
}

$identityOutput = & $Python $ReleaseMetadata --identity-only --root $Root
if ($LASTEXITCODE -ne 0) {
    throw "Immutable release source identity validation failed."
}
$identity = [string]($identityOutput | Select-Object -Last 1) | ConvertFrom-Json
Write-Host "Building immutable release $($identity.release_tag) from $($identity.source_commit.Substring(0, 12))."

# Install the complete reviewed build graph from its SHA-256 lock. This is
# intentionally stronger than checking only the PyInstaller direct pin.
& $Python -m pip install --disable-pip-version-check --require-hashes -r $DevRequirementsLock
if ($LASTEXITCODE -ne 0) {
    throw "The hash-locked desktop build environment could not be installed."
}

$pyInstallerPins = @(
    Select-String -LiteralPath $DevRequirements -Pattern '^pyinstaller==([0-9A-Za-z.+-]+)$'
)
if ($pyInstallerPins.Count -ne 1) {
    throw "dev-requirements.txt must contain exactly one exact PyInstaller pin."
}
$expectedPyInstaller = $pyInstallerPins[0].Matches[0].Groups[1].Value
$installedVersionOutput = & $Python -c "from importlib.metadata import version; print(version('pyinstaller'))"
if ($LASTEXITCODE -ne 0) {
    throw "The selected Python interpreter does not contain the pinned PyInstaller build tool."
}
$installedPyInstaller = [string]($installedVersionOutput | Select-Object -Last 1)
if ($installedPyInstaller.Trim() -ne $expectedPyInstaller) {
    throw "PyInstaller version mismatch: expected $expectedPyInstaller, found $($installedPyInstaller.Trim())."
}

& $Python -m pip check
if ($LASTEXITCODE -ne 0) {
    throw "The selected desktop build environment has inconsistent dependencies."
}

& $Python $Verifier --require-config
if ($LASTEXITCODE -ne 0) {
    throw "Desktop trust-boundary verification failed."
}

& $Python -m PyInstaller --clean --noconfirm $Spec
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
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

if ([string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
    Write-Warning "Treasury.exe is unsigned because this is an explicitly allowed development build."
} else {
    Invoke-CodeSigning -Path $Exe -Thumbprint $SigningCertificateThumbprint
}

# The final installer build creates release-manifest.json and sbom.cdx.json
# after every required artifact exists.
Write-Host "PyInstaller executable created: $Exe"
