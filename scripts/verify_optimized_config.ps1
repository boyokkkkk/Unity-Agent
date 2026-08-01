# Token Efficiency Optimization Verification Script
# Run tests with optimized config and analyze results

param(
    [int]$RunCount = 3,
    [string]$ProjectPath = "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos",
    [string]$EditorPath = "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe",
    [string]$ConfigPath = "configs\kitchen_chaos_optimized.json"
)

Write-Host "=== Token Efficiency Optimization Verification ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Config: $ConfigPath"
Write-Host "Runs: $RunCount"
Write-Host ""

$results = @()

for ($i = 1; $i -le $RunCount; $i++) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $runId = "optimized-run$i-$timestamp"

    Write-Host "=== Run $i/$RunCount ===" -ForegroundColor Green
    Write-Host "Run ID: $runId"
    Write-Host ""

    $startTime = Get-Date

    try {
        & .\.venv\Scripts\game-agent-baseline.exe `
            --project $ProjectPath `
            --config $ConfigPath `
            --editor $EditorPath `
            --run-id $runId `
            --variant innovation

        $exitCode = $LASTEXITCODE
        $endTime = Get-Date
        $duration = ($endTime - $startTime).TotalSeconds

        Write-Host ""
        Write-Host "Exit code: $exitCode" -ForegroundColor $(if($exitCode -eq 0){"Green"}else{"Yellow"})
        Write-Host "Duration: $([math]::Round($duration, 1))s"

        # Analyze results
        $eventsPath = "artifacts\baselines\state-event-v1\$runId\events.jsonl"
        if (Test-Path $eventsPath) {
            $events = Get-Content $eventsPath | ForEach-Object { $_ | ConvertFrom-Json }

            $contextEvents = $events | Where-Object { $_.event -eq "context_assembled" }
            $formatErrors = ($events | Where-Object { $_.event_type -eq "FormatError" }).Count
            $runEnd = $events | Where-Object { $_.event -eq "run_end" } | Select-Object -Last 1

            $tokenGrowth = @()
            $prevTokens = 0
            foreach ($ce in $contextEvents) {
                $growth = $ce.raw_input_tokens - $prevTokens
                $tokenGrowth += $growth
                $prevTokens = $ce.raw_input_tokens
            }

            $avgGrowth = if($tokenGrowth.Count -gt 1) {
                ($tokenGrowth | Select-Object -Skip 1 | Measure-Object -Average).Average
            } else { 0 }

            $result = [PSCustomObject]@{
                RunId = $runId
                ExitStatus = $runEnd.exit_status
                Rounds = $contextEvents.Count
                FormatErrors = $formatErrors
                FinalTokens = $prevTokens
                AvgTokenGrowth = [math]::Round($avgGrowth, 0)
                Duration = [math]::Round($duration, 1)
                WorkingSetFinal = ($contextEvents | Select-Object -Last 1).working_set_metrics.working_set_size
            }

            $results += $result

            Write-Host ""
            Write-Host "Quick Analysis:" -ForegroundColor Cyan
            Write-Host "  Exit Status: $($result.ExitStatus)"
            Write-Host "  Rounds: $($result.Rounds)"
            Write-Host "  Format Errors: $($result.FormatErrors)"
            Write-Host "  Final Tokens: $($result.FinalTokens)"
            Write-Host "  Avg Token Growth: $($result.AvgTokenGrowth) tokens/round"
            Write-Host "  Final Working Set: $($result.WorkingSetFinal)"
        }

    } catch {
        Write-Host "Error: $_" -ForegroundColor Red
    }

    Write-Host ""
    Write-Host "---" -ForegroundColor DarkGray
    Write-Host ""
}

# Summary
Write-Host ""
Write-Host "=== Summary ===" -ForegroundColor Cyan
Write-Host ""

$results | Format-Table -AutoSize

Write-Host ""
Write-Host "=== Statistics ===" -ForegroundColor Cyan
Write-Host ""

$successCount = ($results | Where-Object { $_.ExitStatus -eq "Submitted" }).Count
$formatErrorCount = ($results | Where-Object { $_.ExitStatus -eq "RepeatedFormatError" }).Count

Write-Host "Success Rate: $successCount/$RunCount ($([math]::Round($successCount/$RunCount*100, 1))%)"
Write-Host "FormatError Rate: $formatErrorCount/$RunCount ($([math]::Round($formatErrorCount/$RunCount*100, 1))%)"
Write-Host ""
Write-Host "Avg Token Growth: $([math]::Round(($results.AvgTokenGrowth | Measure-Object -Average).Average, 0)) tokens/round"
Write-Host "Avg Final Tokens: $([math]::Round(($results.FinalTokens | Measure-Object -Average).Average, 0))"
Write-Host "Avg Rounds: $([math]::Round(($results.Rounds | Measure-Object -Average).Average, 1))"
Write-Host ""

# Comparison
Write-Host "=== Comparison with Original Config ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Original (ablation-group1):"
Write-Host "  Avg Token Growth: ~3,000 tokens/round"
Write-Host "  FormatError Rate: 33% (1/3)"
Write-Host "  Success Rate: 0% (0/3)"
Write-Host ""
Write-Host "Optimized (current):"
Write-Host "  Avg Token Growth: $([math]::Round(($results.AvgTokenGrowth | Measure-Object -Average).Average, 0)) tokens/round"
Write-Host "  FormatError Rate: $([math]::Round($formatErrorCount/$RunCount*100, 1))%"
Write-Host "  Success Rate: $([math]::Round($successCount/$RunCount*100, 1))%"
Write-Host ""

$tokenImprovement = (1 - ($results.AvgTokenGrowth | Measure-Object -Average).Average / 3000) * 100
Write-Host "Token Growth Improvement: $([math]::Round($tokenImprovement, 1))%" -ForegroundColor $(if($tokenImprovement -gt 0){"Green"}else{"Red"})

Write-Host ""
Write-Host "Detailed results saved to: artifacts\baselines\state-event-v1\optimized-run*" -ForegroundColor Yellow
