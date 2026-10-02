param(
    [ValidateSet('standalone', 'production', 'demo')][string]$Profile = 'standalone'
)
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'scripts\start_all.ps1') -Profile $Profile
