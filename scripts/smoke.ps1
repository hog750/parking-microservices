$ErrorActionPreference = "Stop"

Write-Host "==> Docker compose up"
docker compose up -d --build

Write-Host "==> Waiting for health endpoints..."
$deadline = (Get-Date).AddMinutes(3)

function Check-Health {
    $urls = @(
        "http://localhost:5001/health",
        "http://localhost:5002/health",
        "http://localhost:5003/health",
        "http://localhost:5004/health",
        "http://localhost:5005/health",
        "http://localhost:5006/health",
        "http://localhost:5008/health",
        "http://localhost:5011/health",
        "http://localhost:5012/health",
        "http://localhost:8080/health"
    )

    foreach ($u in $urls) {
        try {
            $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -ne 200) { return $false }
        } catch {
            return $false
        }
    }
    return $true
}

while ((Get-Date) -lt $deadline) {
    if (Check-Health) {
        Write-Host "Smoke OK"
        docker ps
        exit 0
    }
    Start-Sleep -Seconds 3
}

Write-Host "Smoke FAILED"
docker compose ps
docker compose logs --tail 200
exit 1