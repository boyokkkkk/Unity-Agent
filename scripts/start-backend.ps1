param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$envFile = Join-Path $repositoryRoot ".env"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment not found: $python"
}
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    throw "Environment file not found: $envFile"
}

Push-Location $repositoryRoot
try {
    & $python -m uvicorn game_agent.api.app:app `
        --env-file $envFile `
        --host $HostAddress `
        --port $Port
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
