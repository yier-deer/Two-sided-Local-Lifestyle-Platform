# Compatibility entrypoint. Uses the same bounded, hidden startup as start-all.
param([int]$DockerWaitSeconds = 120)
& (Join-Path $PSScriptRoot 'start-all.ps1') -SkipBuild -DockerWaitSeconds $DockerWaitSeconds
