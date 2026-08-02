param(
    [Parameter(Mandatory=$true)][string]$ProjectPath,
    [Parameter(Mandatory=$true)][string]$EditorPath,
    [ValidateSet("pilot", "formal")][string]$Phase = "pilot",
    [string]$OutputRoot = "artifacts\baselines\context-ablation",
    [string]$WorkspaceRoot = "",
    [string]$SemanticModelCache = "artifacts\semantic-model-cache",
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
if (-not $env:OPENAI_API_KEY) {
    if (-not (Test-Path -LiteralPath ".env")) {
        throw "OPENAI_API_KEY is not set and .env was not found."
    }
    $keyLine = Get-Content -Encoding UTF8 ".env" |
        Where-Object { $_ -match '^\s*OPENAI_API_KEY\s*=' } |
        Select-Object -First 1
    if (-not $keyLine) {
        throw "OPENAI_API_KEY is not present in .env."
    }
    $keyValue = ($keyLine -replace '^\s*OPENAI_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'")
    if (-not $keyValue) {
        throw "OPENAI_API_KEY in .env is empty."
    }
    $env:OPENAI_API_KEY = $keyValue
}
$semanticProbe = & ".\.venv\Scripts\python.exe" -c "import importlib.util; print('available' if importlib.util.find_spec('sentence_transformers') and importlib.util.find_spec('torch') else 'missing')"
if ($LASTEXITCODE -ne 0 -or "$semanticProbe".Trim() -ne "available") {
    throw "Semantic ablation requires sentence-transformers. Install directly with: .\.venv\Scripts\python.exe -m pip install 'sentence-transformers>=3.0,<6'"
}
$semanticModelCacheFull = [System.IO.Path]::GetFullPath($SemanticModelCache)
New-Item -ItemType Directory -Force $semanticModelCacheFull | Out-Null
$env:HF_HOME = Join-Path $semanticModelCacheFull "huggingface"
$env:TORCH_HOME = Join-Path $semanticModelCacheFull "torch"
$env:SENTENCE_TRANSFORMERS_HOME = Join-Path $semanticModelCacheFull "sentence-transformers"
Write-Host "Semantic model cache: $semanticModelCacheFull" -ForegroundColor Cyan
$schedulePath = "configs\context_ablation\$Phase-schedule.json"
$outputRootFull = [System.IO.Path]::GetFullPath($OutputRoot)
New-Item -ItemType Directory -Force $outputRootFull | Out-Null
if (-not $WorkspaceRoot) {
    $WorkspaceRoot = Join-Path $outputRootFull "_workspaces"
}
$workspaceRootFull = [System.IO.Path]::GetFullPath($WorkspaceRoot)
New-Item -ItemType Directory -Force $workspaceRootFull | Out-Null
Write-Host "Disposable workspaces: $workspaceRootFull" -ForegroundColor Cyan
$preflightLog = Join-Path $outputRootFull "preflight-source-compile.log"
Write-Host "Compiling source project before defect injection..." -ForegroundColor Cyan
& $EditorPath -batchmode -quit -projectPath $ProjectPath -logFile $preflightLog
$preflightExit = $LASTEXITCODE
$compilerErrors = @()
if (Test-Path -LiteralPath $preflightLog) {
    $compilerErrors = @(Select-String -Path $preflightLog -Pattern 'error\s+CS\d+' |
        ForEach-Object { $_.Line.Trim() } |
        Select-Object -Unique)
}
if ($preflightExit -ne 0 -or $compilerErrors.Count -gt 0) {
    $details = if ($compilerErrors.Count -gt 0) {
        $compilerErrors -join [Environment]::NewLine
    } else {
        "Unity exited with code $preflightExit. See $preflightLog"
    }
    throw "Source project compile preflight failed. Repair the original project before running the ablation.`n$details"
}
$schedule = Get-Content -Raw -Encoding UTF8 $schedulePath | ConvertFrom-Json
$index = 0
foreach ($run in $schedule.runs) {
    $index++
    $condition = [string]$run.condition
    $taskId = [string]$run.task_id
    $seed = [int]$run.seed
    $sourceConfig = "configs\context_ablation\$($condition.ToLower()).json"
    $config = Get-Content -Raw -Encoding UTF8 $sourceConfig | ConvertFrom-Json
    $config.experiment.seed = $seed
    $config.model.model_kwargs.seed = $seed
    $runId = "{0}-{1:D3}-{2}-{3}-s{4}" -f $Phase, $index, $condition.ToLower(), $taskId, $seed
    $reportPath = Join-Path $OutputRoot "$runId\baseline-report.json"
    if ($Resume -and (Test-Path -LiteralPath $reportPath)) {
        Write-Host "Skipping completed run: $runId" -ForegroundColor DarkGray
        continue
    }
    $runConfig = Join-Path $OutputRoot "$runId-config.json"
    New-Item -ItemType Directory -Force (Split-Path $runConfig) | Out-Null
    $configJson = $config | ConvertTo-Json -Depth 100
    $runConfigFull = [System.IO.Path]::GetFullPath($runConfig)
    [System.IO.File]::WriteAllText(
        $runConfigFull,
        $configJson,
        [System.Text.UTF8Encoding]::new($false)
    )
    & ".\.venv\Scripts\game-agent-baseline.exe" `
        --project $ProjectPath `
        --config $runConfigFull `
        --editor $EditorPath `
        --output-root $OutputRoot `
        --workspace-root $workspaceRootFull `
        --run-id $runId `
        --variant innovation `
        --task-language en `
        --task-id $taskId
    if ($LASTEXITCODE -eq 2) {
        Write-Warning "Invalid experiment: $runId"
    } elseif ($LASTEXITCODE -ne 0) {
        throw "Run failed with exit code ${LASTEXITCODE}: $runId"
    }
}
