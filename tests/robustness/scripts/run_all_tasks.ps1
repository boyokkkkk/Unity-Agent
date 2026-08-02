# 批量执行所有鲁棒性测试任务
# 按顺序执行14个任务并记录结果

$tasks = @("A1", "A2", "A3", "A4", "B1", "B2", "B3", "C1", "C2", "C3", "D1", "D2", "D3", "E1")
$scriptPath = "E:\sysu-course\GameAgent\tests\robustness\run_task.py"
$resultsDir = "E:\sysu-course\GameAgent\tests\robustness\results"

# 确保结果目录存在
if (-not (Test-Path $resultsDir)) {
    New-Item -ItemType Directory -Path $resultsDir | Out-Null
}

Write-Host "=" * 80
Write-Host "开始批量执行鲁棒性测试 - 共 $($tasks.Count) 个任务"
Write-Host "=" * 80
Write-Host ""

$summary = @()
$startTime = Get-Date

foreach ($taskId in $tasks) {
    Write-Host ""
    Write-Host "=" * 80
    Write-Host "执行任务: $taskId"
    Write-Host "=" * 80

    $taskStart = Get-Date

    try {
        # 执行任务
        python $scriptPath $taskId

        $taskEnd = Get-Date
        $duration = ($taskEnd - $taskStart).TotalSeconds

        # 查找最新的结果文件
        $resultFile = Get-ChildItem "$resultsDir\result_${taskId}_*.json" | Sort-Object LastWriteTime -Descending | Select-Object -First 1

        if ($resultFile) {
            $result = Get-Content $resultFile.FullName | ConvertFrom-Json

            $summary += [PSCustomObject]@{
                TaskId = $taskId
                Success = $result.success
                MeetsCriteria = $result.meets_all_criteria
                OverallSuccess = $result.overall_success
                Duration = $duration
                Mutations = $result.mutations_applied
                Tokens = $result.total_tokens
                Error = $result.error
            }

            if ($result.overall_success) {
                Write-Host "✓ 任务 $taskId 成功通过" -ForegroundColor Green
            } else {
                Write-Host "✗ 任务 $taskId 未通过" -ForegroundColor Red
            }
        } else {
            Write-Host "⚠ 任务 $taskId 未找到结果文件" -ForegroundColor Yellow
            $summary += [PSCustomObject]@{
                TaskId = $taskId
                Success = $false
                MeetsCriteria = $false
                OverallSuccess = $false
                Duration = $duration
                Mutations = 0
                Tokens = 0
                Error = "Result file not found"
            }
        }
    } catch {
        Write-Host "✗ 任务 $taskId 执行失败: $_" -ForegroundColor Red
        $summary += [PSCustomObject]@{
            TaskId = $taskId
            Success = $false
            MeetsCriteria = $false
            OverallSuccess = $false
            Duration = 0
            Mutations = 0
            Tokens = 0
            Error = $_.Exception.Message
        }
    }

    Write-Host ""
}

$endTime = Get-Date
$totalDuration = ($endTime - $startTime).TotalSeconds

# 生成汇总报告
Write-Host ""
Write-Host "=" * 80
Write-Host "批量执行完成！"
Write-Host "=" * 80
Write-Host ""

$totalTasks = $summary.Count
$successfulTasks = ($summary | Where-Object { $_.OverallSuccess -eq $true }).Count
$successRate = if ($totalTasks -gt 0) { ($successfulTasks / $totalTasks * 100).ToString("F1") } else { "0.0" }

Write-Host "总任务数: $totalTasks"
Write-Host "成功通过: $successfulTasks"
Write-Host "成功率: ${successRate}%"
Write-Host "总耗时: $($totalDuration.ToString('F2'))s"
Write-Host ""

# 输出详细汇总
Write-Host "详细结果:"
Write-Host ("-" * 80)
$summary | Format-Table -AutoSize

# 保存汇总到文件
$summaryFile = "$resultsDir\batch_summary_$(Get-Date -Format 'yyyyMMdd_HHmmss').json"
$summaryData = @{
    timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    total_tasks = $totalTasks
    successful_tasks = $successfulTasks
    success_rate = "${successRate}%"
    total_duration_seconds = $totalDuration
    tasks = $summary
}

$summaryData | ConvertTo-Json -Depth 10 | Set-Content $summaryFile -Encoding UTF8
Write-Host ""
Write-Host "汇总已保存: $summaryFile"
Write-Host ""
