$ErrorActionPreference = 'SilentlyContinue'
$procIds = @()
try {
    $listener = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    $procIds += $listener | Select-Object -ExpandProperty OwningProcess
} catch {}
$procs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'uvicorn backend\.main:app' }
$procIds += $procs | Select-Object -ExpandProperty ProcessId
$procIds = $procIds | Sort-Object -Unique
foreach ($procId in $procIds) {
    Stop-Process -Id $procId -Force
    Write-Output "stopped business api pid=$procId"
}
