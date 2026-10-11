# Verifies ownership checks against the actual local project services, read-only.
param([string]$PostgresBin = 'E:\PSG\bin', [string]$RedisCli = 'C:\Program Files\Redis\redis-cli.exe')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'native-runtime-checks.ps1')
$env:PGPASSWORD = 'scoutbite123'
$pgData = Join-Path $PSScriptRoot 'runtime\postgres'
$redisData = Join-Path $PSScriptRoot 'runtime\redis'
$psql = Join-Path $PostgresBin 'psql.exe'
Assert-ProjectPostgres -Psql $psql -Port 5433 -ExpectedData $pgData
Assert-ProjectRedis -RedisCli $RedisCli -Port 6380 -ExpectedData $redisData
$postgresRejected = $false
try { Assert-ProjectPostgres -Psql $psql -Port 5433 -ExpectedData (Join-Path $PSScriptRoot 'runtime\unrelated-postgres') } catch { $postgresRejected = $_.Exception.Message -like '*different PostgreSQL runtime*' }
if (-not $postgresRejected) { throw 'Postgres ownership mismatch was accepted.' }
$redisRejected = $false
try { Assert-ProjectRedis -RedisCli $RedisCli -Port 6380 -ExpectedData (Join-Path $PSScriptRoot 'runtime\unrelated-redis') } catch { $redisRejected = $_.Exception.Message -like '*different Redis runtime*' }
if (-not $redisRejected) { throw 'Redis ownership mismatch was accepted.' }
$wrongPortRejected = $false
try { Assert-ProjectPostgres -Psql $psql -Port 5432 -ExpectedData $pgData } catch { $wrongPortRejected = $true }
if (-not $wrongPortRejected) { throw 'An unrelated port was accepted for project PostgreSQL.' }
Write-Host 'PASS: project runtimes accepted; both foreign data directories rejected; no writes performed.'
