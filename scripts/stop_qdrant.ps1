$ErrorActionPreference = 'SilentlyContinue'
$v2Root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $v2Root) ((Split-Path -Leaf $v2Root) + '-data')
$exe = [System.IO.Path]::GetFullPath((Join-Path $dataRoot 'qdrant\qdrant.exe'))
$targets = Get-CimInstance Win32_Process -Filter "Name='qdrant.exe'" |
    Where-Object { [System.IO.Path]::GetFullPath($_.ExecutablePath) -eq $exe }
foreach ($target in $targets) {
    Stop-Process -Id $target.ProcessId -Force
    Write-Output "stopped qdrant pid=$($target.ProcessId)"
}
