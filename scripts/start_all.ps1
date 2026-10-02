param(
    [ValidateSet('standalone', 'production', 'demo')][string]$Profile = 'standalone',
    [int]$FrontendPort = 3000,
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dataRoot = Join-Path (Split-Path -Parent $root) ((Split-Path -Leaf $root) + '-data')
$python = if ($env:HOTLINE_PYTHON) { $env:HOTLINE_PYTHON } else {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    $localPython = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    if ($command) { $command.Source } elseif (Test-Path $localPython) { $localPython } else { '' }
}
if (-not $python -or -not (Test-Path -LiteralPath $python)) {
    throw 'Python not found. Set HOTLINE_PYTHON to a Python 3.11+ executable.'
}
if (-not (Test-Path (Join-Path $root '.env'))) {
    throw 'Missing .env. Copy .env.example to .env and configure it first.'
}
function Get-ConfiguredValue([string]$Name) {
    $processValue = [Environment]::GetEnvironmentVariable($Name, 'Process')
    if ($processValue) { return $processValue }
    $line = Get-Content (Join-Path $root '.env') |
        Where-Object { $_ -match "^\s*$([regex]::Escape($Name))\s*=" } |
        Select-Object -Last 1
    if (-not $line) { return '' }
    return (($line -split '=', 2)[1].Trim()).Trim('"').Trim("'")
}
function Assert-RealLlmConfigured {
    $key = Get-ConfiguredValue 'LLM_API_KEY'
    $model = Get-ConfiguredValue 'LLM_MODEL'
    if (-not $key -or $key -match '^(change_me|your_)') {
        throw 'Real LLM profile requires a configured LLM_API_KEY in .env.'
    }
    if (-not $model -or $model -match '^(change_me|your_)') {
        throw 'Real LLM profile requires a configured LLM_MODEL in .env.'
    }
}
$env:HOTLINE_PYTHON = $python
$databaseUrl = ''
$llmMode = ''
$knowledgeMode = ''
$requireKnowledge = $false

switch ($Profile) {
    'standalone' {
        Assert-RealLlmConfigured
        $dbPath = (Join-Path $dataRoot 'api\hotline_v2.sqlite3').Replace('\', '/')
        New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $dataRoot 'api\hotline_v2.sqlite3')) | Out-Null
        $databaseUrl = "sqlite:///$dbPath"
        $llmMode = 'real'
        $knowledgeMode = 'qdrant'
        $requireKnowledge = $true
    }
    'demo' {
        $dbPath = (Join-Path $dataRoot 'api\hotline_v2_demo.sqlite3').Replace('\', '/')
        New-Item -ItemType Directory -Force -Path (Split-Path (Join-Path $dataRoot 'api\hotline_v2_demo.sqlite3')) | Out-Null
        $databaseUrl = "sqlite:///$dbPath"
        $llmMode = 'mock'
        $knowledgeMode = 'mock'
    }
    'production' {
        Assert-RealLlmConfigured
        $docker = Get-Command docker.exe -ErrorAction SilentlyContinue
        if (-not $docker) { throw 'Production profile requires Docker Desktop (docker.exe not found).' }
        & docker compose --project-directory $root up -d --wait mysql
        if ($LASTEXITCODE -ne 0) { throw 'MySQL failed to start.' }
        $llmMode = 'real'
        $knowledgeMode = 'qdrant'
        $requireKnowledge = $true
    }
}

try {
    # Restart app-layer processes so the selected profile is applied deterministically.
    & (Join-Path $PSScriptRoot 'stop_frontend.ps1') -Port $FrontendPort
    & (Join-Path $PSScriptRoot 'stop_business_api.ps1')
    if ($requireKnowledge) {
        & (Join-Path $PSScriptRoot 'start_qdrant.ps1')
        & (Join-Path $PSScriptRoot 'start_knowledge_api.ps1')
    }
    Push-Location $root
    try {
        if ($databaseUrl) { $env:DATABASE_URL = $databaseUrl }
        & $python -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }
    } finally { Pop-Location }
    & (Join-Path $PSScriptRoot 'start_business_api.ps1') -LLMMode $llmMode -KnowledgeMode $knowledgeMode -DatabaseUrl $databaseUrl
    if (-not $SkipBuild) {
        Push-Location (Join-Path $root 'frontend')
        try {
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
        } finally { Pop-Location }
    }
    & (Join-Path $PSScriptRoot 'start_frontend.ps1') -Port $FrontendPort -Mode prod
    & (Join-Path $PSScriptRoot 'health_check.ps1') -RequireKnowledge:$requireKnowledge -FrontendPort $FrontendPort
    Write-Output "Hotline V2 ready: http://127.0.0.1:$FrontendPort (profile=$Profile)"
} catch {
    Write-Error $_
    throw
}
