# Ablation Experiment Runner
param(
    [int]$StartGroup = 1,
    [int]$EndGroup = 9,
    [int]$Runs = 5,
    [string]$ProjectPath = "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos",
    [string]$EditorPath = "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe",
    [string]$OutputRoot = "artifacts\baselines\state-event-v1",
    [switch]$DryRun
)

# Load environment variables
Get-Content ".env" | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } | ForEach-Object {
    $pair = $_ -split '=', 2
    $key = $pair[0].Trim()
    $value = $pair[1].Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($key, $value, "Process")
}

$groupNames = @{
    1 = "Full System (baseline)"
    2 = "Remove Evidence-Based Recovery"
    3 = "Remove Evidence Artifact Materialization"
    4 = "Remove Dynamic Tool Exposure"
    5 = "Remove Bounded Search Budget"
    6 = "Remove Project Graph Retrieval"
    7 = "Remove Submission Contract"
    8 = "Remove Typed Mutations"
    9 = "Remove Agent Validation Gates"
}

$sep = "=" * 80
Write-Host $sep -ForegroundColor Cyan
Write-Host "Ablation Experiment Runner" -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Cyan
Write-Host ""
Write-Host "Config:"
Write-Host "  Groups: $StartGroup - $EndGroup"
Write-Host "  Runs per group: $Runs"
Write-Host "  Mode: $(if ($DryRun) { 'Dry Run' } else { 'Execute' })"
Write-Host ""

if ($DryRun) {
    Write-Host "DRY RUN MODE - Commands will be displayed but not executed" -ForegroundColor Yellow
    Write-Host ""
}

$totalRuns = ($EndGroup - $StartGroup + 1) * $Runs
$currentRun = 0
$startTime = Get-Date

# Main loop
for ($group = $StartGroup; $group -le $EndGroup; $group++) {
    $configPath = Get-ChildItem "configs\ablation\group$group-*.json" | Select-Object -First 1 -ExpandProperty FullName
    
    if (-not $configPath) {
        Write-Host "ERROR: Config not found for group $group" -ForegroundColor Red
        continue
    }

    Write-Host $sep -ForegroundColor Green
    Write-Host "Group $group - $($groupNames[$group])" -ForegroundColor Green
    Write-Host $sep -ForegroundColor Green
    Write-Host ""

    for ($run = 1; $run -le $Runs; $run++) {
        $currentRun++
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $runId = "ablation-group$group-run$run-$timestamp"

        $progress = [math]::Round(($currentRun / $totalRuns) * 100, 1)

        Write-Host "[$currentRun/$totalRuns - $progress%] Group $group Run $run" -ForegroundColor Cyan
        Write-Host "  Run ID: $runId"

        $cmd = ".\.venv\Scripts\game-agent-baseline.exe --project `"$ProjectPath`" --config `"$configPath`" --editor `"$EditorPath`" --output-root `"$OutputRoot`" --run-id `"$runId`" --variant innovation --task-language en --keep-workspace"

        if ($DryRun) {
            Write-Host "  Command: $cmd" -ForegroundColor Yellow
        } else {
            Write-Host "  Executing..." -ForegroundColor Yellow
            try {
                Invoke-Expression $cmd 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "  SUCCESS" -ForegroundColor Green
                } else {
                    Write-Host "  FAILED (exit code: $LASTEXITCODE)" -ForegroundColor Red
                }
            } catch {
                Write-Host "  ERROR: $_" -ForegroundColor Red
            }
        }
        Write-Host ""
    }
}

$totalTime = (Get-Date) - $startTime
Write-Host $sep -ForegroundColor Cyan
Write-Host "Experiments Complete!" -ForegroundColor Cyan
Write-Host $sep -ForegroundColor Cyan
Write-Host ""
Write-Host "Total runs: $totalRuns"
Write-Host "Total time: $($totalTime.ToString('hh\:mm\:ss'))"
Write-Host ""
Write-Host "Next step: Run data collection"
Write-Host "  python scripts/collect_ablation_results.py"
Write-Host ""
