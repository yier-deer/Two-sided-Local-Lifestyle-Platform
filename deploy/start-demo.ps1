# Standalone ScoutBite demo. No Docker, database or model key is required.
param([int]$Port = 5173, [switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'application-runtime-checks.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$webRoot = Join-Path $projectRoot 'apps\web'
$demoUrl = "http://127.0.0.1:$Port"
$logRoot = Join-Path $PSScriptRoot 'logs'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

try {
    $response = Invoke-WebRequest -Uri $demoUrl -UseBasicParsing -TimeoutSec 2
    if ($response.Content -match 'ScoutBite') {
        Assert-ApplicationRuntime -Port $Port -ExpectedRoot $webRoot -Kind web
        Write-Host "ScoutBite is already available: $demoUrl/#/discover" -ForegroundColor Green
        if ($OpenBrowser) { Start-Process "$demoUrl/#/discover" }
        return
    }
    throw "Port $Port is occupied by another application. Use -Port 5174."
} catch {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $Port is occupied. Use -Port 5174 or stop the existing application."
    }
}

if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) { throw 'Install Node.js LTS first.' }
if (-not (Test-Path -LiteralPath (Join-Path $webRoot 'node_modules\vite\bin\vite.js'))) {
    Push-Location $webRoot
    try { & npm.cmd ci; if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' } } finally { Pop-Location }
}
$viteEntry = Join-Path $webRoot 'node_modules\vite\bin\vite.js'
$stdout = Join-Path $logRoot "web-$Port.out.log"
$stderr = Join-Path $logRoot "web-$Port.err.log"
$process = Start-Process -FilePath (Get-Command node.exe).Source -ArgumentList @("`"$viteEntry`"", '--host', '127.0.0.1', '--port', $Port, '--strictPort') -WorkingDirectory $webRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
$ready = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ($process.HasExited) { throw "Vite exited. Read $stderr" }
    try { $r = Invoke-WebRequest -Uri $demoUrl -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200 -and $r.Content -match 'ScoutBite') { $ready = $true; break } } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ready) { throw "Vite is still starting. Check $stdout and $stderr. PID=$($process.Id)" }
Set-Content -LiteralPath (Join-Path $logRoot "web-$Port.pid") -Value $process.Id -Encoding ASCII
Write-Host "ScoutBite demo: $demoUrl/#/discover" -ForegroundColor Green
Write-Host "Demo guide:    $demoUrl/#/demo"
Write-Host "Web PID: $($process.Id). Logs: $logRoot"
if ($OpenBrowser) { Start-Process "$demoUrl/#/discover" }
