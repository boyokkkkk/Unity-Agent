param(
    [switch]$Delete
)

$ErrorActionPreference = "Stop"
$expectedRoot = [System.IO.Path]::GetFullPath(
    (Join-Path ([System.IO.Path]::GetTempPath()) "game-agent-baselines")
).TrimEnd('\')

if (-not (Test-Path -LiteralPath $expectedRoot)) {
    Write-Host "No baseline workspace cache exists: $expectedRoot" -ForegroundColor Green
    exit 0
}

$resolvedRoot = (Resolve-Path -LiteralPath $expectedRoot).Path.TrimEnd('\')
if ($resolvedRoot -ne $expectedRoot) {
    throw "Refusing cleanup because the resolved target differs from the expected temp root."
}

$workspaces = @(Get-ChildItem -LiteralPath $resolvedRoot -Directory -Force)
Write-Host "Generated workspace root: $resolvedRoot"
Write-Host "Workspace directories: $($workspaces.Count)"
$workspaces | Sort-Object LastWriteTime | Select-Object Name, LastWriteTime | Format-Table -AutoSize

if (-not $Delete) {
    Write-Host "Dry run only. Re-run with -Delete after stopping all experiments." -ForegroundColor Yellow
    exit 0
}

$active = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
    $_.ProcessName -in @("Unity", "python", "game-agent-baseline")
})
if ($active.Count -gt 0) {
    $active | Select-Object Id, ProcessName, StartTime | Format-Table -AutoSize
    throw "Refusing cleanup while Unity/Python/baseline processes are active."
}

foreach ($workspace in $workspaces) {
    $target = [System.IO.Path]::GetFullPath($workspace.FullName)
    if (-not $target.StartsWith($resolvedRoot + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the generated workspace root: $target"
    }
    Remove-Item -LiteralPath $target -Recurse -Force
}

if (@(Get-ChildItem -LiteralPath $resolvedRoot -Force).Count -eq 0) {
    Remove-Item -LiteralPath $resolvedRoot -Force
}
Write-Host "Removed $($workspaces.Count) generated baseline workspace(s)." -ForegroundColor Green
