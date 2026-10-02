param(
    [switch]$RequireKnowledge,
    [int]$FrontendPort = 3000
)
$ErrorActionPreference = 'Stop'
$checks = @(
    @{ Name = 'Business API + database'; Url = 'http://127.0.0.1:8000/api/ready'; Required = $true },
    @{ Name = 'Frontend'; Url = "http://127.0.0.1:$FrontendPort"; Required = $true },
    @{ Name = 'Qdrant'; Url = 'http://127.0.0.1:6333/healthz'; Required = [bool]$RequireKnowledge },
    @{ Name = 'Knowledge API'; Url = 'http://127.0.0.1:8088/health'; Required = [bool]$RequireKnowledge }
)
$failed = @()
foreach ($check in $checks) {
    try {
        $response = Invoke-WebRequest -Uri $check.Url -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 500) { throw "HTTP $($response.StatusCode)" }
        Write-Output "[PASS] $($check.Name) - $($check.Url)"
    } catch {
        $label = if ($check.Required) { 'FAIL' } else { 'SKIP' }
        Write-Output "[$label] $($check.Name) - $($check.Url)"
        if ($check.Required) { $failed += $check.Name }
    }
}
if ($failed.Count) { throw "Required services unavailable: $($failed -join ', ')" }
