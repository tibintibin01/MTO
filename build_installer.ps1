param(
    [string]$PythonPath = "",
    [string]$SigningCertificateThumbprint = $env:MTO_CODE_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampUrl = "https://timestamp.digicert.com",
    [switch]$AllowUnsignedDevelopmentBuild
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = Join-Path $Root "dist"
$Exe = Join-Path $Dist "Treasury.exe"
$BuildScript = Join-Path $Root "build_pyinstaller.ps1"
$ReleaseMetadata = Join-Path $Root "scripts\build_release_metadata.py"
$InnoScript = Join-Path $Root "installer\MTO_Treasury_Setup.iss"
$DefaultConfig = Join-Path $Root "installer\default_config.json"
$IsccCandidates = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$DistConfig = Join-Path $Dist "server_config.json"
$DistCa = Join-Path $Dist "certificates\mto-lan-ca.pem"
$Manifest = Join-Path $Dist "release-manifest.json"
$Sbom = Join-Path $Dist "sbom.cdx.json"

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $Python = Join-Path $Root ".phase5-release-venv\Scripts\python.exe"
} else {
    $Python = (Resolve-Path -LiteralPath $PythonPath -ErrorAction Stop).Path
}

foreach ($required in @(
    $Python,
    $BuildScript,
    $ReleaseMetadata,
    (Join-Path $Root "server_config.json"),
    $InnoScript,
    $DefaultConfig
)) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Required installer input is missing: $required"
    }
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

# Always rebuild so an older EXE that embedded server secrets cannot be packaged.
$buildArguments = @{
    PythonPath = $Python
    TimestampUrl = $TimestampUrl
}
if (-not [string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
    $buildArguments["SigningCertificateThumbprint"] = $SigningCertificateThumbprint
}
if ($AllowUnsignedDevelopmentBuild) {
    $buildArguments["AllowUnsignedDevelopmentBuild"] = $true
}
& $BuildScript @buildArguments
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "The trust-boundary desktop build failed."
}

$identityOutput = & $Python $ReleaseMetadata --identity-only --root $Root
if ($LASTEXITCODE -ne 0) {
    throw "Immutable release source identity validation failed."
}
$identity = [string]($identityOutput | Select-Object -Last 1) | ConvertFrom-Json

$Iscc = $IsccCandidates | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not (Test-Path -LiteralPath $DistConfig -PathType Leaf) -or
    -not (Test-Path -LiteralPath $DistCa -PathType Leaf)) {
    throw "Authenticated TLS client configuration was not staged in dist."
}
if (-not $Iscc) {
    throw "Inno Setup 6 compiler was not found. Install Inno Setup, then run this script again."
}

New-Item -ItemType Directory -Force -Path (Join-Path $Dist "installer") | Out-Null
$isccArguments = @("/DMyAppVersion=$($identity.product_version)")
if ([string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
    if (-not $AllowUnsignedDevelopmentBuild) {
        throw "A managed code-signing certificate is required for the installer."
    }
    Write-Warning "The installer and uninstaller are unsigned for this explicitly allowed development build."
} else {
    $normalizedThumbprint = $SigningCertificateThumbprint.Replace(" ", "").ToUpperInvariant()
    if ($normalizedThumbprint -notmatch '^[0-9A-F]{40,64}$') {
        throw "The code-signing certificate thumbprint format is invalid."
    }
    if ($TimestampUrl -notmatch '^https://') {
        throw "The code-signing timestamp URL must use HTTPS."
    }
    $signTool = Resolve-SignToolPath
    $signCommand = ('"{0}" sign /sha1 {1} /fd SHA256 /td SHA256 /tr "{2}" $f' -f
        $signTool, $normalizedThumbprint, $TimestampUrl)
    $isccArguments += @(
        "/DMTOEnableSigning=1",
        "/SMTOCodeSign=$signCommand"
    )
}
$isccArguments += $InnoScript
& $Iscc @isccArguments
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$Installer = Join-Path $Dist "installer\MTO_Treasury_Setup.exe"
if (-not (Test-Path -LiteralPath $Installer -PathType Leaf)) {
    throw "Installer build finished, but the expected output was not found: $Installer"
}
if (-not [string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
    Assert-ValidAuthenticodeSignature -Path $Exe -ExpectedThumbprint $normalizedThumbprint
    Assert-ValidAuthenticodeSignature -Path $Installer -ExpectedThumbprint $normalizedThumbprint
}

& $Python $ReleaseMetadata --root $Root --distribution $Dist
if ($LASTEXITCODE -ne 0 -or
    -not (Test-Path -LiteralPath $Manifest -PathType Leaf) -or
    -not (Test-Path -LiteralPath $Sbom -PathType Leaf)) {
    throw "Immutable release manifest and SBOM generation failed."
}

Write-Host "Installer created: $Installer"
Write-Host "Release manifest created: $Manifest"
Write-Host "CycloneDX SBOM created: $Sbom"
