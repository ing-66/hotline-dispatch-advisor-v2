param(
    [ValidateSet('', 'mock', 'real')][string]$LLMMode = '',
    [ValidateSet('', 'mock', 'qdrant')][string]$KnowledgeMode = '',
    [string]$DatabaseUrl = ''
)
$ErrorActionPreference = 'Stop'
$v2Root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $v2Root) ((Split-Path -Leaf $v2Root) + '-data')
$logs = Join-Path $dataRoot 'logs'
$python = if ($env:HOTLINE_PYTHON) { $env:HOTLINE_PYTHON } else {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if ($command) { $command.Source } elseif (Test-Path $localPython) { $localPython } else { '' }
}

if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw 'Python not found. Set HOTLINE_PYTHON to a Python 3.11+ executable.'
}
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
    if ($health.status -eq 'ok') { Write-Output 'Business API already healthy on 8000'; return }
} catch {}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
if ($LLMMode) { $env:LLM_GATEWAY_MODE = $LLMMode }
if ($KnowledgeMode) { $env:KNOWLEDGE_GATEWAY_MODE = $KnowledgeMode }
if ($DatabaseUrl) { $env:DATABASE_URL = $DatabaseUrl }
Start-Process -FilePath $python `
    -ArgumentList @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000') `
    -WorkingDirectory $v2Root `
    -RedirectStandardOutput (Join-Path $logs 'business-api.stdout.log') `
    -RedirectStandardError (Join-Path $logs 'business-api.stderr.log') `
    -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
        if ($health.status -eq 'ok') {
            $activeLlm = if ($LLMMode) { $LLMMode } else { 'configured' }
            Write-Output "Business API healthy (LLM mode=$activeLlm)"
            return
        }
    } catch {}
}
throw 'Business API did not become healthy within 30 seconds.'
