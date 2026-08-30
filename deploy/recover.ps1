# -recover.ps1 —— 环境一键恢复（ASCII only，防 PS5.1 编码坑）
# 用法：powershell -ExecutionPolicy Bypass -File deploy\-recover.ps1
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. Docker daemon
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[1/4] starting Docker Desktop..."
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    $ok = $false
    foreach ($i in 1..36) {
        Start-Sleep -Seconds 5
        docker info *> $null
        if ($LASTEXITCODE -eq 0) { $ok = $true; Write-Host "  daemon ready ($($i*5)s)"; break }
    }
    if (-not $ok) { Write-Host "  DAEMON TIMEOUT"; exit 1 }
} else { Write-Host "[1/4] docker daemon OK" }

# 2. containers
docker compose -f "$root\deploy\docker-compose.yml" up -d *> $null
$healthy = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 5
    $statuses = docker compose -f "$root\deploy\docker-compose.yml" ps --format "{{.Status}}" 2>$null
    $up = ($statuses | Where-Object { $_ -match "healthy" }).Count
    if ($up -ge 3) { $healthy = $true; Write-Host "[2/4] containers healthy"; break }
}
if (-not $healthy) { Write-Host "  CONTAINERS NOT HEALTHY"; docker compose -f "$root\deploy\docker-compose.yml" ps; exit 1 }

# 3. shop-api (detached process - survives terminal recycle)
try { $null = Invoke-WebRequest -Uri "http://localhost:8081/actuator/health" -UseBasicParsing -TimeoutSec 3 } catch {
    Write-Host "[3/4] starting shop-api (detached)..."
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\services\shop-api'; java -jar target\shop-api-0.0.1-SNAPSHOT.jar"
}
$apiUp = $false
foreach ($i in 1..20) {
    Start-Sleep -Seconds 3
    try { $r = Invoke-WebRequest -Uri "http://localhost:8081/actuator/health" -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { $apiUp = $true; break } } catch {}
}
Write-Host "[3/4] shop-api $(if ($apiUp) {'UP (8081)'} else {'FAILED'})"

# 4. agent-api (detached)
try { $null = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3 } catch {
    Write-Host "[4/4] starting agent-api (detached)..."
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\services\agent-api'; .\.venv\Scripts\python.exe -m uvicorn main:app --port 8000"
}
$agUp = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 3
    try { $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 3; if ($r.StatusCode -eq 200) { $agUp = $true; break } } catch {}
}
Write-Host "[4/4] agent-api $(if ($agUp) {'UP (8000)'} else {'FAILED'})"
Write-Host "RECOVERY $(if ($apiUp -and $agUp) {'DONE'} else {'INCOMPLETE'})"
