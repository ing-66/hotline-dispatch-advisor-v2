$ErrorActionPreference = 'Stop'
$v2Root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $v2Root) ((Split-Path -Leaf $v2Root) + '-data')
$exe = Join-Path $dataRoot 'qdrant\qdrant.exe'
$storage = Join-Path $dataRoot 'qdrant\storage'
$snapshots = Join-Path $dataRoot 'qdrant-snapshots'
$logs = Join-Path $dataRoot 'logs'

if (-not (Test-Path -LiteralPath $exe)) {
    throw "qdrant.exe not found: $exe (run the migration first)"
}

try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:6333/healthz' -TimeoutSec 2
    if ($health -eq 'healthz check passed') { Write-Output 'Qdrant already healthy on 6333'; return }
} catch {}

New-Item -ItemType Directory -Force -Path $storage, $snapshots, $logs | Out-Null
$env:QDRANT__STORAGE__STORAGE_PATH = $storage
$env:QDRANT__STORAGE__SNAPSHOTS_PATH = $snapshots
$env:QDRANT__SERVICE__HOST = '127.0.0.1'
$env:QDRANT__SERVICE__HTTP_PORT = '6333'
$env:QDRANT__SERVICE__GRPC_PORT = '6334'

Start-Process -FilePath $exe `
    -WorkingDirectory (Split-Path $exe) `
    -RedirectStandardOutput (Join-Path $logs 'qdrant-server.stdout.log') `
    -RedirectStandardError (Join-Path $logs 'qdrant-server.stderr.log') `
    -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:6333/healthz' -TimeoutSec 2
        if ($health -eq 'healthz check passed') { Write-Output 'Qdrant healthy'; return }
    } catch {}
}
throw 'Qdrant did not become healthy within 30 seconds.'
