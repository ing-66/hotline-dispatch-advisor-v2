param([int]$Port = 3000, [string]$Mode = 'dev')
$ErrorActionPreference = 'Stop'
$v2Root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $v2Root) ((Split-Path -Leaf $v2Root) + '-data')
$logs = Join-Path $dataRoot 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$npm = (Get-Command npm.cmd -ErrorAction Stop).Source
if ($Mode -eq 'prod') { $runArgs = @('run', 'start', '--', '-p', [string]$Port, '-H', '127.0.0.1') }
else { $runArgs = @('run', 'dev', '--', '-p', [string]$Port) }
Start-Process -FilePath $npm `
    -ArgumentList $runArgs `
    -WorkingDirectory (Join-Path $v2Root 'frontend') `
    -RedirectStandardOutput (Join-Path $logs 'frontend.stdout.log') `
    -RedirectStandardError (Join-Path $logs 'frontend.stderr.log') `
    -WindowStyle Hidden
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port" -TimeoutSec 2 -UseBasicParsing
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
            Write-Output "Frontend ready on port $Port"
            return
        }
    } catch {}
}
throw 'Frontend did not become ready within 30 seconds.'
