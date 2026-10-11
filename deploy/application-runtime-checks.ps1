# Reuse only listeners launched from this workspace, without stopping foreign processes.
function Assert-ApplicationRuntime([int]$Port, [string]$ExpectedRoot, [string]$Kind, [string]$Profile = 'demo', [string]$VersionFile = '') {
    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
    $runtimeIds = @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($runtimeIds.Count -ne 1) { throw "Port $Port does not identify one project process." }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($runtimeIds[0])"
    if (-not $process -or -not $process.CommandLine) { throw "Cannot verify the process on port $Port." }
    $rootToken = [IO.Path]::GetFullPath($ExpectedRoot).TrimEnd('\').Replace('\', '/')
    $command = $process.CommandLine.Replace('\', '/')
    $belongs = $command.IndexOf($rootToken, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not $belongs -and $Kind -eq 'agent') {
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
        $belongs = $parent -and $parent.CommandLine -and $parent.CommandLine.Replace('\', '/').IndexOf($rootToken, [StringComparison]::OrdinalIgnoreCase) -ge 0
    }
    if (-not $belongs) { throw "Port $Port belongs to another workspace. Stop it yourself or use a different port; no process was terminated." }
    if ($Kind -eq 'shop' -and $command -notlike "*--spring.profiles.active=$Profile*") { throw "Existing shop-api profile differs from $Profile. Stop its old process, then rerun startup." }
    if ($VersionFile -and (Test-Path -LiteralPath $VersionFile) -and (Get-Item -LiteralPath $VersionFile).LastWriteTime -gt $process.CreationDate) { throw "The application on port $Port is older than the current build. Stop the old project process and rerun startup." }
}
