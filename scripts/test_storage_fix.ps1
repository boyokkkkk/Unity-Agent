# Quick test to verify storage fix (no workspace in artifacts)

param(
    [string]$ProjectPath = "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos",
    [string]$EditorPath = "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe",
    [string]$ConfigPath = "configs\kitchen_chaos_optimized.json"
)

Write-Host "=== Testing Storage Fix ===" -ForegroundColor Cyan
Write-Host ""

$runId = "storage-test-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Write-Host "Run ID: $runId" -ForegroundColor Yellow
Write-Host ""

Write-Host "Running experiment..." -ForegroundColor Green
& .\.venv\Scripts\game-agent-baseline.exe `
    --project $ProjectPath `
    --config $ConfigPath `
    --editor $EditorPath `
    --run-id $runId `
    --variant innovation

Write-Host ""
Write-Host "=== Checking Results ===" -ForegroundColor Cyan
Write-Host ""

$artifactDir = "artifacts\baselines\state-event-v1\$runId"

if (Test-Path $artifactDir) {
    # Check if workspace directory exists (should NOT exist)
    $workspaceExists = Test-Path "$artifactDir\workspace"

    # Calculate total artifact size
    $totalSizeMB = [math]::Round((Get-ChildItem $artifactDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 2)

    Write-Host "Artifact Directory: $artifactDir" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Results:" -ForegroundColor Cyan
    Write-Host "  Workspace in artifacts: $workspaceExists" -ForegroundColor $(if($workspaceExists){"Red"}else{"Green"})
    Write-Host "  Total artifact size: $totalSizeMB MB" -ForegroundColor $(if($totalSizeMB -lt 10){"Green"}else{"Red"})
    Write-Host ""

    if ($workspaceExists) {
        Write-Host "FAILED: Workspace directory still exists in artifacts!" -ForegroundColor Red
        Write-Host "The storage fix did not work correctly." -ForegroundColor Red
    } else {
        Write-Host "SUCCESS: No workspace directory in artifacts!" -ForegroundColor Green
        if ($totalSizeMB -lt 10) {
            Write-Host "SUCCESS: Artifact size is reasonable (< 10 MB)" -ForegroundColor Green
        } else {
            Write-Host "WARNING: Artifact size is larger than expected" -ForegroundColor Yellow
        }
    }

    Write-Host ""
    Write-Host "=== File Breakdown ===" -ForegroundColor Cyan
    Get-ChildItem $artifactDir -Recurse -File |
        Group-Object Extension |
        Sort-Object @{Expression={($_.Group | Measure-Object Length -Sum).Sum}; Descending=$true} |
        Select-Object Name, Count, @{Name="SizeMB";Expression={[math]::Round(($_.Group | Measure-Object Length -Sum).Sum / 1MB, 2)}} |
        Format-Table

} else {
    Write-Host "ERROR: Artifact directory not found: $artifactDir" -ForegroundColor Red
    Write-Host "The experiment may have failed to run." -ForegroundColor Red
}

Write-Host ""
Write-Host "Done!" -ForegroundColor Cyan
