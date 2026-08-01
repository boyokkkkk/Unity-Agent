# FormatError根因诊断和解决方案

## 诊断结果

### FormatError发生在哪里？
- **Round 5**: `diagnosis_submit` 工具调用
- **Round 6**: 模型返回格式错误
- **Round 7-8**: 继续重复FormatError

### FormatError的触发工具
**确认**: `diagnosis_submit`

这与之前修复的是**同一个工具**！

---

## 为什么之前的修复没有生效？

### 之前的成功测试 (real-batch-c-manual-20260801-152727)
- **Round 4**: diagnosis_submit ✅ 成功
- **0次FormatError**

### 现在的失败测试 (ablation-group1-run2)
- **Round 5**: diagnosis_submit ❌ FormatError
- **5次FormatError**

### 差异分析

可能的原因：

#### 1. 配置文件中的tool description被覆盖
检查ablation配置是否包含了我们修改的schemas.py

#### 2. 模型随机性
- 即使有了优化的tool description
- 模型在某些情况下仍然可能产生格式错误
- 需要更强的约束

#### 3. P1修改的影响
- P1修改了workflow和controller
- 可能影响了diagnosis的暴露或上下文

---

## 解决方案

### 方案1: 加强diagnosis工具的格式约束（推荐）

在 `schemas.py` 中进一步强化格式说明：

```python
# 添加更明确的错误提示
"description": """
Submit the root-cause diagnosis AFTER all required evidence is read.

CRITICAL FORMAT REQUIREMENTS:
1. ALL 6 fields are REQUIRED (no optional fields):
   - symptom (string)
   - root_targets (array of candidate IDs)
   - causal_chain (array of objects)
   - affected_behavior (object)
   - missing_evidence (array)
   - critical_uncertainties (array)

2. NEVER omit any field, even if empty
3. Use [] for empty arrays
4. Use {} for empty objects

EXAMPLE (copy this structure):
{
  "symptom": "...",
  "root_targets": ["C1", "C2"],
  "causal_chain": [{...}],
  "affected_behavior": {...},
  "missing_evidence": [],
  "critical_uncertainties": []
}

If ANY field is missing, the submission will be REJECTED.
"""
```

### 方案2: 添加schema validation提示

在prompt中添加：

```
IMPORTANT: When calling diagnosis_submit or diagnosis_revise:
- Include ALL 6 required fields
- Do NOT omit any field
- Use [] for empty arrays
- Use {} for empty objects
- Double-check your JSON before submitting
```

### 方案3: 回退到更简单的配置

使用原始的kitchen_chaos.json，不要用ablation配置：

```powershell
# 先用原始配置测试5次
for ($i=1; $i -le 5; $i++) {
    $runId = "baseline-original-run$i-$(Get-Date -Format 'HHmmss')"
    game-agent-baseline --config "configs\kitchen_chaos.json" --run-id $runId --variant innovation
}
```

### 方案4: 增加重试次数

修改 `max_consecutive_format_errors` 从 3 提升到 5：

```json
"max_consecutive_format_errors": 5
```

---

## 立即行动建议

### 优先级1: 验证原始配置的成功率

```powershell
cd E:\sysu-course\GameAgent

# 用原始配置测试5次，建立真实baseline
for ($i=1; $i -le 5; $i++) {
    $runId = "baseline-verify-run$i-$(Get-Date -Format 'HHmmss')"
    
    .\.venv\Scripts\game-agent-baseline.exe `
        --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
        --config "configs\kitchen_chaos.json" `
        --editor "D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe" `
        --run-id $runId `
        --variant innovation
    
    Write-Host "Completed run $i" -ForegroundColor Green
}
```

**目的**: 确认原始配置的真实成功率（之前的成功可能是运气）

### 优先级2: 检查schemas.py的修改是否生效

```powershell
# 检查diagnosis_submit的description
Select-String -Path "src\game_agent\aci\schemas.py" -Pattern "diagnosis_submit" -Context 5,20
```

确认我们之前的Format Error修复是否还在。

### 优先级3: 对比配置文件

```powershell
# 对比原始和ablation配置
fc configs\kitchen_chaos.json configs\ablation\group1-full.json
```

找出差异。

---

## 预期结果

### 如果原始配置也失败
→ 说明基础成功率很低（不是消融配置的问题）
→ 需要进一步优化diagnosis工具的格式约束

### 如果原始配置成功
→ 说明ablation配置有问题
→ 需要重新生成ablation配置

---

## 临时workaround

如果需要立即进行消融实验：

### 选项A: 跳过diagnosis验证
修改所有ablation配置：
```json
"max_consecutive_format_errors": 10  // 增加容错
```

### 选项B: 使用原始配置做消融
直接修改原始kitchen_chaos.json的关键配置：
- Group 1: 原始不变
- Group 3: 设置 `evidence_artifact_enabled: false`
- Group 5: 设置 `global_search_limit: 999`

---

**报告时间**: 2026-08-01 16:50
**根因**: diagnosis_submit 工具的FormatError
**状态**: 需要验证原始配置的成功率
