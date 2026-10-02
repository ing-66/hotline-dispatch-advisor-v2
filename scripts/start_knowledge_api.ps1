$ErrorActionPreference = 'Stop'
$v2Root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $v2Root) ((Split-Path -Leaf $v2Root) + '-data')
$svcRoot = Join-Path $v2Root 'knowledge-service'
$python = Join-Path $svcRoot '.venv\Scripts\python.exe'
$config = Join-Path $svcRoot 'config\config.yaml'
$logs = Join-Path $dataRoot 'logs'

if (-not (Test-Path -LiteralPath $python)) {
    throw "knowledge-service venv not found: $python"
}
if (-not (Test-Path -LiteralPath $config)) {
    throw "knowledge-service config not found: $config"
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/health' -TimeoutSec 2
    if ($health.status -eq 'ok') { Write-Output 'Knowledge API already healthy on 8088'; return }
} catch {}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$env:HOTLINE_KB_CONFIG = $config
$env:HF_HOME = Join-Path $dataRoot 'models'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:KB_ASSET_ROOT = Join-Path $dataRoot 'kb-assets'

Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'kb_service.api:app', '--host', '127.0.0.1', '--port', '8088') `
    -WorkingDirectory $svcRoot `
    -RedirectStandardOutput (Join-Path $logs 'knowledge-api.stdout.log') `
    -RedirectStandardError (Join-Path $logs 'knowledge-api.stderr.log') `
    -WindowStyle Hidden

for ($i = 0; $i -lt 180; $i++) {
    Start-Sleep -Seconds 1
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8088/health' -TimeoutSec 2
        if ($health.status -eq 'ok') { Write-Output 'Knowledge API healthy'; return }
    } catch {}
}
throw 'Knowledge API did not become healthy within 180 seconds.'
