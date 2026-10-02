param([int]$Port = 3000)
$ErrorActionPreference = 'SilentlyContinue'
$procIds = @()
$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
$procIds += $listener | Select-Object -ExpandProperty OwningProcess
$nodeProcesses = Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -match 'next(?:-server)?' -and $_.CommandLine -match '热线派单系统V2' }
$procIds += $nodeProcesses | Select-Object -ExpandProperty ProcessId
foreach ($procId in ($procIds | Sort-Object -Unique)) {
    Stop-Process -Id $procId -Force
    Write-Output "stopped frontend pid=$procId"
}
