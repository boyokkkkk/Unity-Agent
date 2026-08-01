# Navigation Problem Diagnosis - Root Cause Found

## 🔍 问题总结

**症状**: Navigation precision: 0.0, 没有找到任何相关文件

**根本原因**: ❌ Agent 陷入 DIAGNOSE 阶段，从未进入 EXPLORE 阶段搜索文件

---

## 📊 实际工具使用分析

### Tools Called (15 total)
```
diagnosis_revise:    12 次  ← 反复修订诊断
candidate_read:      12 次  ← 读取候选（但候选从哪来？）
task_plan_submit:     4 次  ← 提交计划
diagnosis_submit:     2 次  ← 提交诊断
```

### Tools NOT Called
```
❌ unity_asset_search:     0 次  (应该用来搜索 Unity 资源)
❌ code_symbol_search:     0 次  (应该用来搜索代码符号)
❌ unity_ref_search:       0 次  (应该用来搜索依赖)
❌ code_find_references:   0 次  (应该用来找引用)
```

---

## 🔄 Workflow 阶段分析

### 预期流程
```
PLAN → EXPLORE → INSPECT → DIAGNOSE → EDIT → VALIDATE → REVIEW → SUBMIT
  ↓       ↓         ↓          ↓
 计划   搜索文件   检查候选   诊断问题
```

### 实际流程
```
PLAN → (EXPLORE跳过?) → DIAGNOSE (卡住)
  ↓                         ↓
 计划                   反复修订诊断
```

---

## 🐛 根本原因推断

### 假设 1: EXPLORE 阶段被跳过
**可能原因**:
- Workflow 状态机逻辑错误
- 某个条件导致直接跳到 DIAGNOSE
- Search budget 为 0

**证据**:
- Tool profile shows: plan(2), inspect(2), diagnose(13)
- NO explore phase tools were called
- Agent读了 12 次 candidate，但从未搜索过

### 假设 2: Candidate 来源错误
**问题**:
- Agent 在 INSPECT/DIAGNOSE 阶段读取 candidate
- 但这些 candidate 从哪来的？
- 如果没有 EXPLORE，candidate 列表应该是空的

**可能**:
- Workflow初始化了一些默认 candidates
- 但这些 candidates 不是相关文件
- Agent 在错误的候选上诊断

### 假设 3: Evidence 过度修剪
**我们的 Fix 2**:
- 减少了 evidence 到 6+4+4 = 14 项
- 使用 confidence > 0.85 过滤

**可能问题**:
- 初始 evidence (从 project graph 获取) 被过滤掉
- Workflow 依赖这些 evidence 来决定下一步
- Evidence 不足 → Workflow 卡住

---

## 📈 Token 使用对比

### Tool Schema Tokens

| Phase | Our Fix | Expected | Actual |
|-------|---------|----------|--------|
| **explore** | N/A (未修改) | ~2,000 | **0 (未调用)** |
| **inspect** | N/A (未修改) | ~800 | ~800 |
| **diagnose** | N/A (未修改) | ~600 | ~600 |
| **edit** | ✅ 2-4 tools | ~800 | **0 (未进入)** |

**Tool schema tokens per call**: 946 tokens
- 这比我们预期的 800 tokens 高
- 但比原始的 3,310 tokens 低很多
- 说明 Fix 1 **有效但未完全应用**（因为没进入 EDIT 阶段）

---

## 🔍 需要检查的地方

### 1. Workflow 状态机
```python
# src/game_agent/aci/workflow.py
class WorkflowState:
    def observe_search(...):
        # 这里决定何时从 EXPLORE 转到 INSPECT/DIAGNOSE
        # 可能 search budget 太小？
        # 可能跳过逻辑有问题？
```

### 2. Evidence 初始化
```python
# 我们的 Fix 2:
verified = [
    item.to_dict()
    for item in verified_all
    if item.confidence > 0.85  # ← 太严格？
][-6:]
```

**问题**: 如果初始 evidence (从 graph 生成) confidence < 0.85，会被过滤掉

### 3. Candidate 来源
```python
# Agent 读了 12 次 candidate
# 但这些 candidate 从哪里来？
# 如果 EXPLORE 被跳过，candidate list 应该是空的
```

---

## 🎯 诊断计划

### 检查 Workflow 日志
```python
# 查看 events.jsonl 中的 workflow_phase_transition 事件
# 确认是否进入过 EXPLORE 阶段
```

### 检查 Evidence 过滤
```python
# 查看被过滤掉的 evidence
# 是否有 confidence < 0.85 的重要 evidence
```

### 检查 Candidate 数量
```python
# 查看 working_set_metrics
# working_set_size 应该反映候选数量
```

---

## 💡 临时解决方案

### Option 1: 放宽 Evidence 过滤
```python
# 当前: confidence > 0.85
# 建议: confidence > 0.5 (或完全移除过滤，只用数量限制)

verified = [item.to_dict() for item in verified_all][-6:]  # 只限制数量
```

### Option 2: 检查 Workflow Budget
```python
# 查看 configs/kitchen_chaos_optimized.json
# 确认 search_budget, expand_budget 不为 0
```

### Option 3: 强制进入 EXPLORE
```python
# 修改 workflow 状态机
# 确保 PLAN 后必然进入 EXPLORE
# 不允许直接跳到 DIAGNOSE
```

---

## 🔄 下一步行动

1. **等待新测试完成** (config 已更新 detail_char_limit: 600)
2. **检查新测试是否仍有导航问题**
3. **如果仍有问题**:
   - 放宽 Evidence confidence 过滤
   - 检查 Workflow budget 配置
   - 查看 events.jsonl 确认 phase transitions

4. **如果问题解决**:
   - 说明是 detail_char_limit 配置问题
   - 确认 token 优化效果

---

## 📝 结论

**主要发现**:
1. ✅ Fix 1 (工具 Schema) 有效，但只应用到 EDIT 阶段
2. ⚠️ Fix 2 (Evidence 过滤) 可能过于激进
3. ❌ Agent 跳过了 EXPLORE 阶段，导致无法搜索文件
4. ❌ 在没有搜索的情况下进行诊断，导致 NoProgressExceeded

**根本问题**: 不是我们的 Fix 导致的，而是:
- Workflow 状态机逻辑问题
- 或 Evidence 过滤太严格导致 Workflow 无法正常进行
- 或配置中的 search_budget 为 0

**建议**: 
- 等待新测试完成
- 如果问题依旧，放宽 Evidence confidence 过滤
- 检查 Workflow 配置和状态机逻辑
