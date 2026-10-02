$ErrorActionPreference = 'SilentlyContinue'
$procIds = @()
try {
    $listener = Get-NetTCPConnection -LocalPort 8088 -State Listen -ErrorAction SilentlyContinue
    $procIds += $listener | Select-Object -ExpandProperty OwningProcess
} catch {}
$kbProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'kb_service\.api:app' }
$procIds += $kbProcs | Select-Object -ExpandProperty ProcessId
$procIds = $procIds | Sort-Object -Unique
foreach ($procId in $procIds) {
    Stop-Process -Id $procId -Force
    Write-Output "stopped knowledge api pid=$procId"
}
