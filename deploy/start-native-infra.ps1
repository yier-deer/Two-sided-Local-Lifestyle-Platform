# Project-isolated real PostgreSQL and Redis when Docker Desktop is unavailable.
param(
    [string]$PostgresBin = 'E:\PSG\bin',
    [string]$RedisServer = 'C:\Program Files\Redis\redis-server.exe',
    [int]$PostgresPort = 5433,
    [int]$RedisPort = 6380
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'native-runtime-checks.ps1')
$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $PSScriptRoot 'runtime'
$logRoot = Join-Path $PSScriptRoot 'logs'
$pgData = Join-Path $runtimeRoot 'postgres'
$redisData = Join-Path $runtimeRoot 'redis'
foreach ($targetPath in @($runtimeRoot, $pgData, $redisData, $logRoot)) {
    $resolvedTarget = [IO.Path]::GetFullPath($targetPath)
    if (-not $resolvedTarget.StartsWith([IO.Path]::GetFullPath($PSScriptRoot) + '\')) { throw 'Runtime directory is outside deploy.' }
    New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
}
$initdb = Join-Path $PostgresBin 'initdb.exe'
$pgctl = Join-Path $PostgresBin 'pg_ctl.exe'
$psql = Join-Path $PostgresBin 'psql.exe'
foreach ($binary in @($initdb, $pgctl, $psql, $RedisServer)) { if (-not (Test-Path -LiteralPath $binary)) { throw "Missing native binary: $binary. Pass -PostgresBin and -RedisServer to your installed tools." } }

if (-not (Test-Path -LiteralPath (Join-Path $pgData 'PG_VERSION'))) {
    if ((Get-ChildItem -LiteralPath $pgData -Force).Count -gt 0) { throw 'Postgres runtime directory is nonempty but uninitialized; inspect it before continuing.' }
    $passwordFile = Join-Path $runtimeRoot 'init-password.tmp'
    Set-Content -LiteralPath $passwordFile -Value 'scoutbite123' -Encoding ASCII
    try { & $initdb -D $pgData -U scoutbite --encoding=UTF8 --locale=C --auth-host=scram-sha-256 --auth-local=scram-sha-256 "--pwfile=$passwordFile"; if ($LASTEXITCODE -ne 0) { throw 'Project PostgreSQL initialization failed.' } } finally { Remove-Item -LiteralPath $passwordFile -ErrorAction SilentlyContinue }
}
$env:PGPASSWORD = 'scoutbite123'
$env:PGCONNECT_TIMEOUT = '3'
$pgReady = $false
try { & $psql -h 127.0.0.1 -p $PostgresPort -U scoutbite -d postgres -w -Atc 'SELECT 1' *> $null; $pgReady = $LASTEXITCODE -eq 0 } catch {}
if (-not $pgReady) {
    if (Get-NetTCPConnection -LocalPort $PostgresPort -State Listen -ErrorAction SilentlyContinue) { throw "PostgreSQL port $PostgresPort is occupied by a different service." }
    $pgArguments = @('-D', "`"$pgData`"", '-l', "`"$(Join-Path $logRoot 'postgres.log')`"", '-o', "`"-h 127.0.0.1 -p $PostgresPort`"", '-w', 'start')
    $pgStart = Start-Process -FilePath $pgctl -ArgumentList $pgArguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'pg-start.out.log') -RedirectStandardError (Join-Path $logRoot 'pg-start.err.log') -PassThru
    if (-not $pgStart.WaitForExit(20000)) { throw 'PostgreSQL startup is still pending. Read deploy/logs/postgres.log before retrying.' }
    # Windows PowerShell can leave ExitCode null after WaitForExit with redirected pipes.
    # Verify the authenticated server instead of mistaking that wrapper state for failure.
    & $psql -h 127.0.0.1 -p $PostgresPort -U scoutbite -d postgres -w -Atc 'SELECT 1' *> $null
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL startup failed; read deploy/logs/pg-start.err.log.' }
}
Assert-ProjectPostgres -Psql $psql -Port $PostgresPort -ExpectedData $pgData
$databaseExists = & $psql -h 127.0.0.1 -p $PostgresPort -U scoutbite -d postgres -w -Atc "SELECT 1 FROM pg_database WHERE datname='scoutbite'"
if ($LASTEXITCODE -ne 0) { throw 'Could not connect to isolated PostgreSQL.' }
if ($databaseExists -ne '1') { & $psql -h 127.0.0.1 -p $PostgresPort -U scoutbite -d postgres -w -c 'CREATE DATABASE scoutbite'; if ($LASTEXITCODE -ne 0) { throw 'Could not create project database.' } }
Write-Host "Real PostgreSQL ready on 127.0.0.1:$PostgresPort (isolated from the existing 5432 service)." -ForegroundColor Green

$redisCli = Join-Path (Split-Path -Parent $RedisServer) 'redis-cli.exe'
if (-not (Test-Path -LiteralPath $redisCli)) { throw 'redis-cli.exe must be next to redis-server.exe.' }
$redisReady = $false
try { $redisReady = (& $redisCli -h 127.0.0.1 -p $RedisPort PING 2>$null) -eq 'PONG' } catch {}
if (-not $redisReady) {
    if (Get-NetTCPConnection -LocalPort $RedisPort -State Listen -ErrorAction SilentlyContinue) { throw "Redis port $RedisPort is occupied." }
    $redisArguments = @('--bind', '127.0.0.1', '--port', $RedisPort, '--dir', "`"$redisData`"", '--dbfilename', 'dump.rdb', '--appendonly', 'yes')
    $redisStart = Start-Process -FilePath $RedisServer -ArgumentList $redisArguments -WorkingDirectory $redisData -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot 'redis.out.log') -RedirectStandardError (Join-Path $logRoot 'redis.err.log') -PassThru
    Set-Content -LiteralPath (Join-Path $logRoot 'redis.pid') -Value $redisStart.Id -Encoding ASCII
    for ($attempt = 0; $attempt -lt 10; $attempt++) { try { if ((& $redisCli -h 127.0.0.1 -p $RedisPort PING 2>$null) -eq 'PONG') { $redisReady = $true; break } } catch {}; if ($redisStart.HasExited) { break }; Start-Sleep -Seconds 1 }
    if (-not $redisReady) { throw 'Redis startup failed. Read deploy/logs/redis.err.log.' }
}
Assert-ProjectRedis -RedisCli $redisCli -Port $RedisPort -ExpectedData $redisData
Write-Host "Real Redis ready on 127.0.0.1:$RedisPort (project persistence in deploy/runtime/redis)." -ForegroundColor Green
