# 消融实验执行指南

## 准备工作完成情况

### ✅ 已完成
1. **配置文件**: 9个消融配置已创建在 `configs/ablation/`
2. **数据收集脚本**: `scripts/collect_ablation_results.py`
3. **自动化运行脚本**: `scripts/run_ablation_experiments.ps1`

---

## 实验设计

### 9个实验组

| 组 | 名称 | 修改内容 | 预期成功率 |
|----|------|----------|-----------|
| 1 | group1-full | 完整系统 (baseline) | 70-80% |
| 2 | group2-no-p1 | 移除P1 Evidence-Based Recovery | 40-50% |
| 3 | group3-no-evidence | 移除P0+P1 Evidence Materialization | 10-20% |
| 4 | group4-no-dynamic-tools | 移除Dynamic Tool Exposure | 60-70% |
| 5 | group5-no-search-budget | 移除Bounded Search Budget | 60-70% |
| 6 | group6-no-graph | 移除Project Graph | 60-70% |
| 7 | group7-no-contract | 移除Submission Contract | 60-70% |
| 8 | group8-no-typed-mutations | 移除Typed Mutations | 60-70% |
| 9 | group9-no-validation | 移除Validation | 60-70% |

### 每组运行5次
- 控制模型随机性
- 计算平均成功率和标准差

### 预计总耗时
- 9组 × 5次 × 2分钟 = **90分钟**

---

## 执行步骤

### 方案A: 自动化执行（推荐）

#### 1. 试运行（验证配置）
```powershell
# 进入项目目录
cd E:\sysu-course\GameAgent

# 试运行，只显示命令不执行
.\scripts\run_ablation_experiments.ps1 -DryRun
```

#### 2. 执行所有实验
```powershell
# 正式运行所有9组，每组5次
.\scripts\run_ablation_experiments.ps1
```

#### 3. 部分执行（如果需要）
```powershell
# 只运行组1-3（核心消融）
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 3

# 只运行组3的5次（验证最大消融）
.\scripts\run_ablation_experiments.ps1 -StartGroup 3 -EndGroup 3

# 每组只运行3次（快速验证）
.\scripts\run_ablation_experiments.ps1 -Runs 3
```

---

### 方案B: 手动执行（如果自动化脚本有问题）

#### 加载环境变量
```powershell
Get-Content ".env" | Where-Object { $_ -match '^\s*[A-Za-z_][A-Za-z0-9_]*\s*=' } | ForEach-Object {
    $pair = $_ -split '=', 2
    $key = $pair[0].Trim()
    $value = $pair[1].Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($key, $value, "Process")
}
```

#### 执行单次实验
```powershell
# Group 1, Run 1
$runId = "ablation-group1-run1-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

.\.venv\Scripts\game-agent-baseline.exe `
    --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
    --config "configs\ablation\group1-full.json" `
    --editor "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe" `
    --output-root "artifacts\baselines\state-event-v1" `
    --run-id $runId `
    --variant innovation `
    --keep-workspace
```

#### 循环执行
```powershell
# 执行所有实验
for ($group = 1; $group -le 9; $group++) {
    $config = Get-ChildItem "configs\ablation\group$group-*.json" | Select-Object -First 1 -ExpandProperty FullName
    
    for ($run = 1; $run -le 5; $run++) {
        $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $runId = "ablation-group$group-run$run-$timestamp"
        
        Write-Host "Running Group $group Run $run..." -ForegroundColor Cyan
        
        .\.venv\Scripts\game-agent-baseline.exe `
            --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
            --config $config `
            --editor "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe" `
            --output-root "artifacts\baselines\state-event-v1" `
            --run-id $runId `
            --variant innovation `
            --keep-workspace
        
        Write-Host "Completed Group $group Run $run" -ForegroundColor Green
        Write-Host ""
    }
}
```

---

## 数据收集与分析

### 实验完成后执行

```powershell
# 收集并分析结果
python scripts/collect_ablation_results.py
```

### 输出内容

**1. 控制台输出**:
- 各组汇总统计
- 成功率对比
- 相对Baseline的变化
- Token使用对比

**2. CSV文件**:
- `ablation_results_YYYYMMDD_HHMMSS.csv` - 所有实验的详细结果
- `ablation_summary_YYYYMMDD_HHMMSS.csv` - 按组汇总的统计

### 关键指标

**主要指标**:
- `verified_success`: 是否通过验证（成功率）
- `total_tokens`: Token使用量
- `rounds`: 执行轮次
- `exit_status`: 退出状态

**次要指标**:
- `reached_edit`: 是否到达EDIT阶段
- `reached_validate`: 是否到达VALIDATE阶段
- `mutation_failures`: Mutation失败次数
- `format_errors`: 格式错误次数

---

## 注意事项

### ⚠️ 需要代码修改的组

部分消融组需要代码级别的修改（配置文件无法控制）：

#### Group 2: 移除P1
**修改**: `src/game_agent/aci/workflow.py`
```python
# 回退observe_mutation_failure方法到P0版本
# 移除diagnostic参数和基于error_code的智能恢复
def observe_mutation_failure(self, *, tool: str, message: str, paths: list[str] | None = None):
    # ... P0的简单实现
    self.stage_directive = (
        "Mutation failed; re-read or expand the target evidence, then revise the diagnosis. "
        + message
    )
```

#### Group 4: 移除Dynamic Tool Exposure
**修改**: `src/game_agent/aci/exposure.py`
```python
# 所有阶段返回全部工具
def _workflow_exposure(workflow, working_paths, *, pending_stage=""):
    return _exposure("all_phases", ALL_TOOLS, "All tools available")
```

#### Group 7: 移除Submission Contract
**修改**: `src/game_agent/aci/controller.py`
```python
# guard_submission始终返回None
def guard_submission(self):
    return None  # 允许任意时间提交
```

### 💡 建议

**如果不想修改代码**:
1. 先运行 Group 1, 3, 5, 6, 8, 9（不需要代码修改）
2. 这6组已经足够验证核心假设
3. Group 3（移除P0+P1）是最关键的

**核心消融优先**:
```powershell
# 只运行最关键的3组
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 1  # baseline
.\scripts\run_ablation_experiments.ps1 -StartGroup 3 -EndGroup 3  # 最大消融
.\scripts\run_ablation_experiments.ps1 -StartGroup 5 -EndGroup 9  # 其他可配置的消融
```

---

## 故障排查

### 问题1: 环境变量未加载
**症状**: "Missing credentials" 错误
**解决**: 确保 `.env` 文件存在且包含 `OPENAI_API_KEY`

### 问题2: Unity编辑器路径错误
**症状**: "Unity Editor not found"
**解决**: 检查 `--editor` 路径是否正确

### 问题3: 项目路径错误
**症状**: "Project not found"
**解决**: 检查 `--project` 路径是否指向Unity项目根目录

### 问题4: 配置文件缺失
**症状**: "config file not found"
**解决**: 
```powershell
# 检查配置文件是否存在
Get-ChildItem configs\ablation\
```

---

## 实验监控

### 实时查看进度
```powershell
# 在另一个终端查看最新的运行日志
Get-ChildItem artifacts\baselines\state-event-v1\ablation-* | 
    Sort-Object LastWriteTime -Descending | 
    Select-Object -First 1 | 
    ForEach-Object { Get-Content "$_\events.jsonl" -Tail 20 }
```

### 查看已完成的实验
```powershell
# 统计已完成的实验数量
$completed = Get-ChildItem artifacts\baselines\state-event-v1\ablation-* | 
             Where-Object { Test-Path "$_\baseline-report.json" }
Write-Host "已完成: $($completed.Count) 个实验"
```

---

## 快速开始命令

### 最简单的执行方式

```powershell
# 1. 进入项目目录
cd E:\sysu-course\GameAgent

# 2. 执行所有实验（90分钟）
.\scripts\run_ablation_experiments.ps1

# 3. 收集分析结果
python scripts/collect_ablation_results.py
```

### 快速验证（30分钟）

```powershell
# 只运行核心3组，每组3次
.\scripts\run_ablation_experiments.ps1 -StartGroup 1 -EndGroup 1 -Runs 3
.\scripts\run_ablation_experiments.ps1 -StartGroup 3 -EndGroup 3 -Runs 3
.\scripts\run_ablation_experiments.ps1 -StartGroup 6 -EndGroup 6 -Runs 3

python scripts/collect_ablation_results.py
```

---

## 预期结果示例

### 成功率对比
```
Group 1 (完整系统): 75.0%
Group 2 (移除P1): 45.0% (-30%)
Group 3 (移除P0+P1): 15.0% (-60%)  ← 验证核心价值
Group 4 (移除Dynamic Tools): 68.0% (-7%)
Group 5 (移除Search Budget): 72.0% (-3%)
Group 6 (移除Graph): 70.0% (-5%)
Group 7 (移除Contract): 65.0% (-10%)
Group 8 (移除Typed Mutations): 62.0% (-13%)
Group 9 (移除Validation): 55.0% (-20%)
```

### 论文结论
- **Evidence Materialization (P0+P1)** 是核心创新，贡献60%性能提升
- **P1** 在P0基础上额外贡献30%
- **工作流设计**（Dynamic Tools, Contract等）贡献10-20%

---

## 文档创建时间
2026-08-01

## 准备就绪状态
✅ 配置文件已创建
✅ 脚本已就绪
✅ 执行指南完整

## 下一步
执行消融实验并收集数据！
