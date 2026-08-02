param(
    [string]$ConfigRoot = "configs\context_ablation"
)

$ErrorActionPreference = "Stop"

$pilotPath = Join-Path $ConfigRoot "pilot-schedule.json"
$formalPath = Join-Path $ConfigRoot "formal-schedule.json"
$configPaths = 0..4 | ForEach-Object { Join-Path $ConfigRoot "c$_.json" }

$requiredPaths = @($pilotPath, $formalPath) + @($configPaths)
$missing = @($requiredPaths | Where-Object { -not (Test-Path -LiteralPath $_) })
if ($missing.Count -gt 0) {
    throw "Missing context-ablation files: $($missing -join ', ')"
}

$pilotDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $pilotPath | ConvertFrom-Json
$formalDocument = Get-Content -Raw -Encoding UTF8 -LiteralPath $formalPath | ConvertFrom-Json
$pilotSchedule = @($pilotDocument.runs)
$formalSchedule = @($formalDocument.runs)

$pilotConditions = @($pilotSchedule | ForEach-Object { $_.condition } | Sort-Object -Unique)
$formalConditions = @($formalSchedule | ForEach-Object { $_.condition } | Sort-Object -Unique)
$formalTasks = @($formalSchedule | ForEach-Object { $_.task_id } | Sort-Object -Unique)
$formalSeeds = @($formalSchedule | ForEach-Object { $_.seed } | Sort-Object -Unique)

$conditionGroups = @($formalSchedule | Group-Object condition)
$taskGroups = @($formalSchedule | Group-Object task_id)
$seedGroups = @($formalSchedule | Group-Object seed)

$scheduleChecks = [ordered]@{
    PilotRuns         = $pilotSchedule.Count -eq 10
    FormalRuns        = $formalSchedule.Count -eq 150
    PilotConditions   = $pilotConditions.Count -eq 5
    FiveConditions    = $formalConditions.Count -eq 5
    SixTasks          = $formalTasks.Count -eq 6
    FiveSeeds         = $formalSeeds.Count -eq 5
    ConditionGroups   = $conditionGroups.Count -eq 5
    ConditionBalance  = $conditionGroups.Count -eq 5 -and @($conditionGroups | Where-Object Count -ne 30).Count -eq 0
    TaskGroups        = $taskGroups.Count -eq 6
    TaskBalance       = $taskGroups.Count -eq 6 -and @($taskGroups | Where-Object Count -ne 25).Count -eq 0
    SeedGroups        = $seedGroups.Count -eq 5
    SeedBalance       = $seedGroups.Count -eq 5 -and @($seedGroups | Where-Object Count -ne 30).Count -eq 0
}

$scheduleChecks.GetEnumerator() |
    ForEach-Object { [pscustomobject]@{ Check = $_.Key; Passed = $_.Value } } |
    Format-Table -AutoSize

if ($scheduleChecks.Values -contains $false) {
    Write-Host "Observed counts:" -ForegroundColor Yellow
    [pscustomobject]@{
        PilotRuns = $pilotSchedule.Count
        FormalRuns = $formalSchedule.Count
        PilotConditions = $pilotConditions.Count
        FormalConditions = $formalConditions.Count
        FormalTasks = $formalTasks.Count
        FormalSeeds = $formalSeeds.Count
    } | Format-List
    throw "Context-ablation schedule validation failed."
}

$configs = @($configPaths | ForEach-Object {
    Get-Content -Raw -Encoding UTF8 -LiteralPath $_ | ConvertFrom-Json
})
$graphHashes = @($configs | ForEach-Object { $_.context.graph_sha256 } | Sort-Object -Unique)
$vectors = @($configs | ForEach-Object {
    "{0}|{1}|{2}|{3}" -f `
        $_.context.graph_retrieval_enabled,
        $_.context.semantic_search_enabled,
        $_.context.causal_edges_enabled,
        $_.context.context_assembly_enabled
} | Sort-Object -Unique)

$configChecks = [ordered]@{
    ConfigCount = $configs.Count -eq 5
    EnglishTasks = @($configs | Where-Object { $_.experiment.task_language -ne "en" }).Count -eq 0
    TokenLimit = @($configs | Where-Object { $_.experiment.max_total_tokens -ne 163840 }).Count -eq 0
    Temperature = @($configs | Where-Object { $_.model.model_kwargs.temperature -ne 0.0 }).Count -eq 0
    ContextEnabled = @($configs | Where-Object { -not $_.context.enabled }).Count -eq 0
    FixedGraph = $graphHashes.Count -eq 1
    UniqueTreatments = $vectors.Count -eq 5
}

$configChecks.GetEnumerator() |
    ForEach-Object { [pscustomobject]@{ Check = $_.Key; Passed = $_.Value } } |
    Format-Table -AutoSize

if ($configChecks.Values -contains $false) {
    throw "Context-ablation fixed-control validation failed."
}

Write-Host "PASS: context-ablation configs and schedules are valid." -ForegroundColor Green
