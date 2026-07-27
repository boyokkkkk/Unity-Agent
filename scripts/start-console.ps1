param(
    [string]$Config = "configs/kitchen_chaos.json",
    [string]$Project = "",
    [string]$Artifacts = "artifacts/console",
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ConsoleArguments
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python virtual environment not found: $python"
}

$arguments = @(
    "-m", "game_agent.console",
    "--config", $Config,
    "--artifacts", $Artifacts
)
if ($Project) {
    $arguments += @("--project", $Project)
}
if ($ConsoleArguments) {
    $arguments += $ConsoleArguments
}

Push-Location $repositoryRoot
try {
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
