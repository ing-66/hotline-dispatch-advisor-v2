param([int]$FrontendPort = 3000, [switch]$KeepDatabase)
$ErrorActionPreference = 'Continue'
& (Join-Path $PSScriptRoot 'stop_frontend.ps1') -Port $FrontendPort
& (Join-Path $PSScriptRoot 'stop_business_api.ps1')
& (Join-Path $PSScriptRoot 'stop_knowledge_api.ps1')
& (Join-Path $PSScriptRoot 'stop_qdrant.ps1')
if (-not $KeepDatabase -and (Get-Command docker.exe -ErrorAction SilentlyContinue)) {
    $root = Split-Path -Parent $PSScriptRoot
    & docker compose --project-directory $root down
}
Write-Output 'Hotline V2 stopped.'
