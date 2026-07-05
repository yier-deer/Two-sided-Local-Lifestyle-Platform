# deploy/start-all.ps1 —— ScoutBite 一键启动全家桶
# 用法：在项目根目录执行  powershell -ExecutionPolicy Bypass -File deploy\start-all.ps1
# 每个服务独立窗口，Ctrl+C 可单独停；电脑重启后从这开始

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 1. Docker Desktop（已在跑就跳过）
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[1/5] 启动 Docker Desktop（等待 daemon 就绪）..." -ForegroundColor Cyan
    Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    do { Start-Sleep -Seconds 5; docker info *> $null } until ($LASTEXITCODE -eq 0)
} else {
    Write-Host "[1/5] Docker 已在运行" -ForegroundColor Green
}

# 2. 三大件（PG/Redis/MinIO）
Write-Host "[2/5] 启动三大件..." -ForegroundColor Cyan
docker compose -f "$root\deploy\docker-compose.yml" up -d

# 3. shop-api（jar 若不存在先打包）
$jar = "$root\services\shop-api\target\shop-api-0.0.1-SNAPSHOT.jar"
if (-not (Test-Path $jar)) {
    Write-Host "[3/5] 首次运行：打包 shop-api（约 40 秒）..." -ForegroundColor Cyan
    Push-Location "$root\services\shop-api"
    mvn -s maven-settings.xml -DskipTests -q package
    Pop-Location
}
Write-Host "[3/5] 启动 shop-api :8081（独立窗口）" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\services\shop-api'; java -jar target\shop-api-0.0.1-SNAPSHOT.jar"

# 4. agent-api
Write-Host "[4/5] 启动 agent-api :8000（独立窗口）" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\services\agent-api'; .\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000"

# 5. web 前端
Write-Host "[5/5] 启动 web :5173（独立窗口）" -ForegroundColor Cyan
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\apps\web'; npm run dev"

Write-Host ""
Write-Host "全部拉起。验收入口：" -ForegroundColor Yellow
Write-Host "  Swagger  http://localhost:8081/swagger-ui.html"
Write-Host "  Agent    http://localhost:8000/docs"
Write-Host "  Web      http://localhost:5173"
Write-Host "  MinIO    http://localhost:9001（scoutbite / scoutbite123）"
