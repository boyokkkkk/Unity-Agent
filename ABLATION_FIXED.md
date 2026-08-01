# 消融实验 - 已修复问题

## 已修复的问题

✅ **问题1**: UTF-8 BOM编码 - 已修复
✅ **问题2**: project-graph路径解析 - 已改为绝对路径

---

## 🚀 现在可以执行的命令

### 测试单次运行（推荐先测试）

```powershell
cd E:\sysu-course\GameAgent

# 测试Group 1一次（约2-3分钟）
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 1 -Runs 1
```

**预期**: 应该看到实验正常运行，最后显示 SUCCESS 或 FAILED (取决于任务是否完成)

---

### 快速验证核心假设（30分钟）

```powershell
cd E:\sysu-course\GameAgent

# Group 1: 完整系统 - 3次
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 1 -Runs 3

# Group 3: 移除P0+P1 - 3次
.\scripts\run_ablation_experiments.ps1 -StartGroup 3 -EndGroup 3 -Runs 3

# 收集结果
python scripts/collect_ablation_results.py
```

---

### 完整实验（不需要代码修改的组，60分钟）

```powershell
cd E:\sysu-course\GameAgent

# 运行6组实验
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 1 -Runs 5
.\scripts\run_ablation_experiments.ps1 -StartGroup 3 -EndGroup 3 -Runs 5
.\scripts\run_ablation_experiments.ps1 -StartGroup 5 -EndGroup 6 -Runs 5
.\scripts\run_ablation_experiments.ps1 -StartGroup 8 -EndGroup 9 -Runs 5

# 收集结果
python scripts/collect_ablation_results.py
```

---

## 📊 查看实验结果

### 实时监控

```powershell
# 查看已完成的实验数量
$completed = Get-ChildItem artifacts\baselines\state-event-v1\ablation-* | 
             Where-Object { Test-Path "$_\baseline-report.json" }
Write-Host "已完成: $($completed.Count) 个实验"

# 查看最新实验的成功状态
$latest = Get-ChildItem artifacts\baselines\state-event-v1\ablation-* | 
          Sort-Object LastWriteTime -Descending | 
          Select-Object -First 1

if (Test-Path "$latest\baseline-report.json") {
    $report = Get-Content "$latest\baseline-report.json" | ConvertFrom-Json
    Write-Host "最新实验: $($latest.Name)"
    Write-Host "验证成功: $($report.verified_success)" -ForegroundColor $(if ($report.verified_success) { "Green" } else { "Red" })
}
```

---

## 🔍 故障排查

### 如果仍然失败

1. **检查环境变量**
```powershell
$env:OPENAI_API_KEY
$env:OPENAI_BASE_URL
```
应该输出API密钥和URL

2. **手动运行baseline命令**
```powershell
Get-Content ".env" | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } | ForEach-Object {
    $pair = $_ -split '=', 2
    $key = $pair[0].Trim()
    $value = $pair[1].Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($key, $value, "Process")
}

.\.venv\Scripts\game-agent-baseline.exe `
    --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
    --config "configs\ablation\group1-full.json" `
    --editor "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe" `
    --output-root "artifacts\baselines\state-event-v1" `
    --run-id "manual-test" `
    --variant innovation
```

3. **查看详细日志**
```powershell
# 找到最新的运行目录
$latest = Get-ChildItem artifacts\baselines\state-event-v1\ablation-* | 
          Sort-Object LastWriteTime -Descending | 
          Select-Object -First 1

# 查看events日志
Get-Content "$latest\events.jsonl" -Tail 20
```

---

## ✅ 配置修复状态

- ✅ 所有9个配置文件的BOM已移除
- ✅ project-graph路径已改为绝对路径
- ✅ 脚本语法已修复

**准备就绪！**

---

**更新时间**: 2026-08-01 16:15
**状态**: 配置已修复，可以执行实验
