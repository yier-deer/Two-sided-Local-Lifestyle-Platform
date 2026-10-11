# Real-service mode: infrastructure + Java + Python + web, with bounded waits.
param(
    [switch]$SkipBuild,
    [switch]$SkipDockerStart,
    [int]$DockerWaitSeconds = 120,
    [ValidateSet('Auto','Docker','Native')][string]$Infrastructure = 'Auto',
    [string]$PostgresBin = 'E:\PSG\bin',
    [string]$RedisServer = 'C:\Program Files\Redis\redis-server.exe',
    [ValidateSet('demo','default')][string]$Profile = 'demo'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'application-runtime-checks.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$logRoot = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

function Test-HttpReady([string]$Url) {
    try { $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2; return ($r.StatusCode -eq 200) } catch { return $false }
}
function Test-DockerReady {
    $probe = Start-Process -FilePath (Get-Command docker.exe).Source -ArgumentList @('info', '--format', '{{.ServerVersion}}') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'docker-probe.out.log') -RedirectStandardError (Join-Path $logRoot 'docker-probe.err.log') -PassThru
    if (-not $probe.WaitForExit(6000)) { $probe.Kill(); return $false }
    $probe.Refresh()
    $serverVersion = [string](Get-Content -LiteralPath (Join-Path $logRoot 'docker-probe.out.log') -Raw -ErrorAction SilentlyContinue)
    $serverVersion = $serverVersion.Trim()
    return ($probe.ExitCode -eq 0 -or $serverVersion -match '^\d+\.\d+(?:\.\d+)?$')
}
function Wait-HttpReady([string]$Url, [System.Diagnostics.Process]$Process, [int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        if (Test-HttpReady $Url) { return }
        if ($Process.HasExited) { throw "Service exited before readiness: $Url. See $logRoot" }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)
    throw "Service did not become ready: $Url. See $logRoot"
}
if ($Infrastructure -eq 'Auto') {
    if ((Test-Path -LiteralPath (Join-Path $PostgresBin 'pg_ctl.exe')) -and (Test-Path -LiteralPath $RedisServer) -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'runtime\postgres\PG_VERSION'))) {
        $Infrastructure = 'Native'
    } elseif ((Get-Command docker.exe -ErrorAction SilentlyContinue) -and (Test-DockerReady)) {
        $Infrastructure = 'Docker'
    } elseif ((Test-Path -LiteralPath (Join-Path $PostgresBin 'pg_ctl.exe')) -and (Test-Path -LiteralPath $RedisServer)) {
        $Infrastructure = 'Native'
    } else {
        $Infrastructure = 'Docker'
    }
    Write-Host "Selected infrastructure: $Infrastructure"
}
if ($Infrastructure -eq 'Native') {
    & (Join-Path $PSScriptRoot 'start-native-infra.ps1') -PostgresBin $PostgresBin -RedisServer $RedisServer
    Write-Host '[1/5] Isolated native PostgreSQL and Redis ready.' -ForegroundColor Green
    Write-Host '[2/5] MinIO is optional: image uploads are outside this demo.' -ForegroundColor Green
} else {
if (-not (Get-Command docker.exe -ErrorAction SilentlyContinue)) { throw 'Docker is missing. Use -Infrastructure Native with installed PostgreSQL/Redis, or deploy/start-demo.ps1.' }
$dockerReady = Test-DockerReady
if (-not $dockerReady -and -not $SkipDockerStart) {
    $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $desktop) { Write-Host 'Starting Docker Desktop in the background...'; Start-Process -FilePath $desktop -WindowStyle Hidden }
}
$deadline = (Get-Date).AddSeconds([Math]::Max(0, $DockerWaitSeconds))
while (-not $dockerReady -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 3
    $dockerReady = Test-DockerReady
}
if (-not $dockerReady) { throw "Docker daemon is unavailable. See $logRoot\docker-probe.err.log. For an immediate demo run: powershell -ExecutionPolicy Bypass -File deploy\start-demo.ps1" }
Write-Host '[1/5] Docker daemon ready.' -ForegroundColor Green
& docker.exe compose -f (Join-Path $PSScriptRoot 'docker-compose.yml') up -d --wait --wait-timeout 90
if ($LASTEXITCODE -ne 0) { throw 'Infrastructure failed to start. Existing volumes have not been reset.' }
Write-Host '[2/5] PostgreSQL, Redis and MinIO ready.' -ForegroundColor Green
}

$shopRoot = Join-Path $projectRoot 'services\shop-api'
$jar = Join-Path $shopRoot 'target\shop-api-0.0.1-SNAPSHOT.jar'
$needsBuild = -not (Test-Path -LiteralPath $jar)
if (-not $needsBuild -and -not $SkipBuild) {
    $sourceFiles = @((Get-ChildItem -LiteralPath (Join-Path $shopRoot 'src') -Recurse -File), (Get-Item -LiteralPath (Join-Path $shopRoot 'pom.xml')))
    $newestSource = $sourceFiles | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $needsBuild = $newestSource.LastWriteTime -gt (Get-Item -LiteralPath $jar).LastWriteTime
}
if ($needsBuild) {
    Push-Location $shopRoot
    try { & mvn.cmd -B -ntp -s maven-settings.xml package; if ($LASTEXITCODE -ne 0) { throw 'Java build or tests failed.' } } finally { Pop-Location }
}
if (-not (Test-HttpReady 'http://127.0.0.1:8081/actuator/health')) {
    $shopProcess = Start-Process -FilePath (Get-Command java.exe).Source -ArgumentList @('-jar', "`"$jar`"", "--spring.profiles.active=$Profile") -WorkingDirectory $shopRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'shop.out.log') -RedirectStandardError (Join-Path $logRoot 'shop.err.log') -PassThru
    Set-Content -LiteralPath (Join-Path $logRoot 'shop.pid') -Value $shopProcess.Id -Encoding ASCII
    Wait-HttpReady 'http://127.0.0.1:8081/actuator/health' $shopProcess 90
} else {
    Assert-ApplicationRuntime -Port 8081 -ExpectedRoot $shopRoot -Kind shop -Profile $Profile -VersionFile $jar
}
Write-Host '[3/5] shop-api ready :8081.' -ForegroundColor Green

$agentRoot = Join-Path $projectRoot 'services\agent-api'
$agentPython = Join-Path $agentRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $agentPython)) {
    & python -m venv (Join-Path $agentRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Python virtual environment creation failed.' }
    & $agentPython -m pip install -r (Join-Path $agentRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Agent dependencies could not be installed.' }
}
if (-not (Test-HttpReady 'http://127.0.0.1:8000/health')) {
    $agentProcess = Start-Process -FilePath $agentPython -ArgumentList @('-m', 'uvicorn', 'main:app', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $agentRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'agent.out.log') -RedirectStandardError (Join-Path $logRoot 'agent.err.log') -PassThru
    Set-Content -LiteralPath (Join-Path $logRoot 'agent.pid') -Value $agentProcess.Id -Encoding ASCII
    Wait-HttpReady 'http://127.0.0.1:8000/health' $agentProcess 45
} else {
    $agentSource = Get-ChildItem -LiteralPath $agentRoot -Filter '*.py' | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    Assert-ApplicationRuntime -Port 8000 -ExpectedRoot $agentRoot -Kind agent -VersionFile $agentSource.FullName
}
Write-Host '[4/5] agent-api ready :8000.' -ForegroundColor Green
& (Join-Path $PSScriptRoot 'start-demo.ps1')
Write-Host '[5/5] Web ready. Switch the top-right data mode to Real Service and log in.' -ForegroundColor Green
Write-Host 'Web: http://127.0.0.1:5173/#/discover'
Write-Host 'Swagger: http://127.0.0.1:8081/swagger-ui.html'
Write-Host 'Agent: http://127.0.0.1:8000/docs'
