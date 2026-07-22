param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F:.]+$')]
    [string]$ServerIp
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$backendEnvPath = Join-Path $projectRoot '.env'
$frontendEnvPath = Join-Path $projectRoot 'frontend\.env.local'
$snapshotDirectory = Join-Path $projectRoot 'portal_data'
$snapshotPath = Join-Path $snapshotDirectory 'portal_snapshot_latest.json'

function Read-EnvValues([string]$Path) {
    $values = @{}
    if (-not (Test-Path -LiteralPath $Path)) { return $values }
    foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
        $clean = $line.Trim()
        if (-not $clean -or $clean.StartsWith('#') -or -not $clean.Contains('=')) { continue }
        $parts = $clean.Split('=', 2)
        $values[$parts[0].Trim()] = $parts[1].Trim()
    }
    return $values
}

function Test-UsableSecret([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value) -or $Value.Length -lt 32) { return $false }
    return $Value -notmatch '(?i)change|replace|generate|example|placeholder|<'
}

function New-PortalSecret {
    $bytes = New-Object byte[] 48
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function Set-EnvValues([string]$Path, [hashtable]$Updates, [string]$SectionTitle) {
    $lines = New-Object 'System.Collections.Generic.List[string]'
    if (Test-Path -LiteralPath $Path) {
        foreach ($existingLine in [System.IO.File]::ReadAllLines($Path)) {
            $lines.Add($existingLine)
        }
    }
    $remaining = @{}
    foreach ($key in $Updates.Keys) { $remaining[$key] = [string]$Updates[$key] }

    for ($index = 0; $index -lt $lines.Count; $index++) {
        $clean = $lines[$index].Trim()
        if (-not $clean -or $clean.StartsWith('#') -or -not $clean.Contains('=')) { continue }
        $key = $clean.Split('=', 2)[0].Trim()
        if ($remaining.ContainsKey($key)) {
            $lines[$index] = "$key=$($remaining[$key])"
            $remaining.Remove($key)
        }
    }

    if ($remaining.Count -gt 0) {
        if ($lines.Count -gt 0 -and $lines[$lines.Count - 1].Trim()) { $lines.Add('') }
        $lines.Add("# $SectionTitle")
        foreach ($key in ($remaining.Keys | Sort-Object)) {
            $lines.Add("$key=$($remaining[$key])")
        }
    }

    $directory = Split-Path -Parent $Path
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    $tempPath = Join-Path $directory ('.env.' + [Guid]::NewGuid().ToString('N') + '.tmp')
    try {
        [System.IO.File]::WriteAllText($tempPath, (($lines -join "`n").TrimEnd() + "`n"), [System.Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $tempPath -Destination $Path -Force
    } finally {
        if (Test-Path -LiteralPath $tempPath) { Remove-Item -LiteralPath $tempPath -Force }
    }
}

$backendValues = Read-EnvValues $backendEnvPath
$lookupSecret = [string]$backendValues['MTO_PORTAL_LOOKUP_SECRET']
$generatedSecret = -not (Test-UsableSecret $lookupSecret)
if ($generatedSecret) { $lookupSecret = New-PortalSecret }

Set-EnvValues $backendEnvPath @{
    MTO_PORTAL_LOOKUP_SECRET = $lookupSecret
    MTO_PORTAL_SNAPSHOT_DIR = $snapshotDirectory
} 'Local public portal snapshot'

Set-EnvValues $frontendEnvPath @{
    NEXT_PUBLIC_API_URL = "http://${ServerIp}:8001"
    MTO_PORTAL_LOOKUP_SECRET = $lookupSecret
    MTO_PORTAL_SNAPSHOT_PATH = $snapshotPath
    MTO_PORTAL_MAX_SNAPSHOT_AGE_HOURS = '36'
} 'Auto-generated local portal configuration - do not commit'

[System.IO.Directory]::CreateDirectory($snapshotDirectory) | Out-Null
Write-Host "[PORTAL] Local snapshot path configured: $snapshotPath"
if ($generatedSecret) {
    Write-Host '[PORTAL] Generated a new lookup secret. A fresh snapshot is required.'
} else {
    Write-Host '[PORTAL] Preserved the existing lookup secret.'
}
