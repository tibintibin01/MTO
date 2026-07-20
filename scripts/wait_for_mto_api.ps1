param(
    [ValidateRange(5, 300)]
    [int]$TimeoutSeconds = 90,
    [string]$HealthUrl = "http://127.0.0.1:8001/readyz"
)

$ErrorActionPreference = "Stop"
$deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)

Write-Host "Waiting for the updated MTO API to become ready..."
while ([DateTime]::UtcNow -lt $deadline) {
    try {
        $response = Invoke-WebRequest `
            -Uri $HealthUrl `
            -UseBasicParsing `
            -TimeoutSec 3
        if ($response.StatusCode -eq 200) {
            Write-Host "MTO API readiness check passed."
            exit 0
        }
    }
    catch {
        # Database connections and application routes may still be starting.
    }
    Start-Sleep -Seconds 2
}

Write-Error "MTO API did not become ready within $TimeoutSeconds seconds."
exit 1
