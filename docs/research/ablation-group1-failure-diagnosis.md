# Ablation Group 1 失败诊断报告

## 诊断时间
2026-08-01 16:40

## 失败的3次运行

### Run 1: ablation-group1-run1-20260801-162517
- **Exit Status**: `TotalTokenLimitExceeded`
- **Total Tokens**: 108,856 / 120,000
- **验证成功**: ❌ `verified_success: false`
- **关键问题**:
  - 找到了正确文件 `GameStartCountdownUI.cs`
  - 创建了evidence artifact
  - 进行了2次mutation
  - 但**未完成任务** - `hidden_validation_passed: false`
  - Token用尽前未能修复问题

### Run 2: ablation-group1-run2-20260801-163035  
- **Exit Status**: `RepeatedFormatError`
- **Format Errors**: 5次
- **验证成功**: ❌ `verified_success: false`
- **关键问题**:
  - **FormatError再次出现！**
  - 这说明之前的Format Error修复可能不完整
  - 或者模型在某些情况下仍然产生格式错误

### Run 3: ablation-group1-run3-20260801-163439
- **Exit Status**: `NoProgressExceeded`
- **Total Tokens**: 93,807 / 120,000
- **验证成功**: ❌ `verified_success: false`
- **关键问题**:
  - 没有进行任何mutation (`mutation_calls: 0`)
  - 卡在diagnose阶段
  - 触发了no-progress保护机制

---

## 核心问题分析

### 问题1: 任务完成率低
**现象**: 3次运行都没有成功完成任务
- Run 1: 进入EDIT阶段，但修改不正确
- Run 2: FormatError导致无法提交diagnosis
- Run 3: 连EDIT阶段都没进入

**对比之前成功的测试**:
- `real-batch-c-manual-20260801-152727`: `TotalTokenLimitExceeded`，但至少进入了EDIT阶段
- `p0-fixed-20260801-144745`: `verified_success: false`，但workflow正常运行

### 问题2: FormatError又出现了
**Run 2有5次FormatError**，这说明：
1. 之前的修复（优化tool description）不够全面
2. 或者模型在某些情况下仍然产生格式错误
3. 需要进一步诊断是哪个工具产生了FormatError

### 问题3: No Progress问题
**Run 3连mutation都没有执行**，可能原因：
1. diagnosis阶段反复失败
2. diagnosis被阻止（missing evidence？）
3. 陷入某种循环

---

## 与之前成功测试的对比

### 之前成功的测试 (real-batch-c-manual-20260801-152727)
```
Exit Status: TotalTokenLimitExceeded
verified_success: false
但: 
- 0次FormatError
- diagnosis_submit成功（Round 4）
- diagnosis_revise成功（Round 7, 8）
- 进入EDIT阶段
- 创建了evidence artifact
```

### 现在的ablation测试
```
Run 1: TotalTokenLimitExceeded (108K tokens)
  - 进入EDIT，但修改不正确
  - 2次mutation
  
Run 2: RepeatedFormatError
  - 5次FormatError ← 问题！
  
Run 3: NoProgressExceeded
  - 0次mutation
  - 卡在diagnose
```

---

## 可能的原因

### 1. 配置文件问题
ablation配置可能与原始kitchen_chaos.json有差异：
- 某些字段在复制时丢失或改变
- JSON depth不够导致嵌套对象被截断

### 2. 模型随机性
- 模型在不同运行中表现不稳定
- 需要更多样本（3次不够）

### 3. 之前测试的"成功"是偶然
- 之前的测试也没有`verified_success: true`
- 只是0 FormatError + 到达EDIT阶段
- 实际任务完成率可能本来就很低

### 4. P1代码引入了新问题
- P1修改了workflow.py和controller.py
- 可能引入了回归问题

---

## 建议的调试步骤

### 步骤1: 对比配置文件
```powershell
# 对比原始配置和ablation配置
$original = Get-Content "configs\kitchen_chaos.json" -Raw | ConvertFrom-Json
$ablation = Get-Content "configs\ablation\group1-full.json" -Raw | ConvertFrom-Json

# 检查关键字段是否一致
Compare-Object ($original | ConvertTo-Json -Depth 20) ($ablation | ConvertTo-Json -Depth 20)
```

### 步骤2: 使用原始配置测试
```powershell
# 用原始配置运行5次，看看成功率
for ($i=1; $i -le 5; $i++) {
    $runId = "baseline-original-run$i"
    game-agent-baseline --config "configs\kitchen_chaos.json" --run-id $runId --variant innovation
}
```

### 步骤3: 分析FormatError来源
```powershell
# 查看Run 2的详细events
$events = Get-Content "artifacts\baselines\state-event-v1\ablation-group1-run2-20260801-163035\events.jsonl"
$events | Select-String "FormatError" -Context 2
```

### 步骤4: 检查是否P1引入回归
回退P1修改，用P0代码测试：
- 暂时回退workflow.py的observe_mutation_failure
- 用P0版本测试

---

## 初步结论

**当前的ablation测试失败率很高，无法进行有效的消融实验。**

问题可能在于：
1. ❌ 配置文件复制有问题
2. ❌ FormatError未完全修复
3. ❌ 基础成功率本来就很低（需要更多baseline样本）
4. ❌ P1可能引入了回归

**建议**: 
1. 先用原始kitchen_chaos.json测试5次，建立真实的baseline
2. 修复FormatError问题
3. 确保ablation配置与原始配置完全一致
4. 再开始消融实验

---

**报告创建时间**: 2026-08-01 16:40
**状态**: 需要进一步调试
