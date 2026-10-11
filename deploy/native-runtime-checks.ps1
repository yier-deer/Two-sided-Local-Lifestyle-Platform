# Bind the listener to the project process/data directory before any writes.
# Process/pid evidence avoids native Windows tools losing Chinese path characters.
function Assert-ProjectPostgres([string]$Psql, [int]$Port, [string]$ExpectedData) {
    $errorMessage = "Port $Port is a different PostgreSQL runtime; no project database will be created or seeded."
    $pidFile = Join-Path $ExpectedData 'postmaster.pid'
    if (-not (Test-Path -LiteralPath $pidFile)) { throw $errorMessage }
    $pidLines = @(Get-Content -LiteralPath $pidFile)
    if ($pidLines.Count -lt 4 -or [int]$pidLines[3] -ne $Port) { throw $errorMessage }
    $runtimePid = [int]$pidLines[0]
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    if (-not ($listeners | Where-Object { $_.OwningProcess -eq $runtimePid })) { throw $errorMessage }
    $runtimeProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$runtimePid"
    $expectedRoot = [IO.Path]::GetFullPath($ExpectedData).TrimEnd('\').Replace('\', '/')
    if (-not $runtimeProcess -or $runtimeProcess.Name -ne 'postgres.exe' -or -not $runtimeProcess.CommandLine -or $runtimeProcess.CommandLine.Replace('\', '/').IndexOf($expectedRoot, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw $errorMessage }
}

function Assert-ProjectRedis([string]$RedisCli, [int]$Port, [string]$ExpectedData) {
    $errorMessage = "Port $Port is a different Redis runtime; no project cache keys will be written."
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $runtimeIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($runtimeIds.Count -ne 1) { throw $errorMessage }
    $runtimeProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtimeIds[0])"
    $expectedRoot = [IO.Path]::GetFullPath($ExpectedData).TrimEnd('\')
    if (-not $runtimeProcess -or $runtimeProcess.Name -ne 'redis-server.exe' -or $runtimeProcess.CommandLine -notlike "*--dir `"$expectedRoot`"*") { throw $errorMessage }
}
