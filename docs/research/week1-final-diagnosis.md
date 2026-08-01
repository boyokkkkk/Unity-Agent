# Week 1 Token Optimization - Final Diagnosis

## 📊 测试结果对比

### Run 1: detail_char_limit = 1200 (配置未更新)
- **轮数**: 15 轮
- **Total tokens**: 190,235 / 200,000
- **Avg tokens/round**: 10,239
- **退出**: `NoProgressExceeded` during diagnose
- **问题**: Agent 跳过 EXPLORE，卡在 DIAGNOSE 阶段

### Run 2: detail_char_limit = 600 (配置已更新)  
- **轮数**: **2 轮**❌
- **Total tokens**: 12,507 / 200,000
- **Avg tokens/round**: 6,253
- **退出**: `NoProgressExceeded` during **plan**
- **问题**: Agent 在 PLAN 阶段就失败了

---

## 🚨 严重问题发现

### 问题：Fix 4 过于激进

**detail_char_limit: 1200 → 600 的影响**:

```
Run 1 (1200 chars):
  Round 1:  5,731 tokens
  Round 2:  6,392 tokens
  ✅ Agent 能够完成 plan 并进入后续阶段

Run 2 (600 chars):
  Round 1:  5,570 tokens  (相似)
  Round 2:  6,216 tokens  (相似)
  ❌ Agent 在 plan 阶段就 NoProgressExceeded
```

**分析**:
- Token 使用相似（都是 ~6k）
- 但 600 chars 限制导致 **candidate details 信息不足**
- Agent 无法基于不完整的信息制定有效计划
- **过早终止**

---

## 💡 根本问题诊断

### 问题 1: Evidence 过滤太严格

**当前实现**:
```python
verified = [
    item.to_dict()
    for item in verified_all
    if item.confidence > 0.85  # ← 太严格
][-6:]
```

**影响**:
- 初始 evidence（从 project graph 生成）可能 confidence < 0.85
- 被过滤掉后，agent 缺少基础信息
- 导致 workflow 无法正常推进

### 问题 2: Detail 限制太小

**当前实现**:
```python
detail_char_limit: 600  # ← 太小
```

**影响**:
- Candidate details 被截断
- Agent 看不到完整的类/方法结构
- 无法制定有效的计划或诊断

### 问题 3: 优化配置本身有问题

**Config: kitchen_chaos_optimized.json**:
```json
{
  "max_working_set_entries": 12,
  "max_candidate_details": 3,
  "max_evidence_items": 12
}
```

**可能问题**:
- 这些参数已经很激进
- 再加上我们的代码修剪（evidence 14→6）
- **双重限制导致信息严重不足**

---

## 🔄 修复策略调整

### 立即回滚 Fix 2 和 Fix 4

**Fix 2: Evidence 修剪** - 需要调整
```python
# 当前（太严格）:
verified = [... if item.confidence > 0.85][-6:]

# 建议（更宽松）:
verified = [item.to_dict() for item in verified_all][-12:]  # 恢复原始数量
# 或
verified = [... if item.confidence > 0.7][-8:]  # 降低阈值，保留更多
```

**Fix 4: Detail 限制** - 需要回滚
```python
# 当前:
detail_char_limit: 600  # ← 太小

# 建议:
detail_char_limit: 1200  # 恢复到优化配置原值
# 或
detail_char_limit: 900   # 折中方案
```

### 保留 Fix 1 和 Fix 3

**Fix 1: 工具 Schema** - ✅ 有效
- EDIT 阶段从 11→2-4 工具
- 节省 ~2,500 tokens
- **保留**

**Fix 3: 验证摘要** - ✅ 有效
- 成功验证不保存详情
- 节省 ~1,400 tokens
- **保留**

---

## 📋 新的修复方案

### 方案 A: 保守修复（推荐）

**只保留 Fix 1 和 Fix 3**:
- ✅ Fix 1: 工具 Schema 减少
- ❌ Fix 2: 移除 Evidence 过滤（恢复原始逻辑）
- ✅ Fix 3: 验证摘要优化  
- ❌ Fix 4: 移除 detail_char_limit 修改（使用配置值）

**预期效果**:
- Token 节省: -3,900/round (-28%)
- Agent 能正常运行
- 任务完成率提升

### 方案 B: 渐进优化

**调整而非移除 Fix 2 和 Fix 4**:

**Fix 2 调整**:
```python
# 降低 confidence 阈值，增加保留数量
verified = [
    item.to_dict()
    for item in verified_all
    if item.confidence > 0.7  # 从 0.85 降到 0.7
][-8:]  # 从 6 增加到 8

active = [item.to_dict() for item in active_all][-6:]  # 从 4 增加到 6
suggested = [item.to_dict() for item in suggested_all][:6:]  # 从 4 增加到 6

# Total: 8+6+6 = 20 items (vs 当前 6+4+4 = 14)
```

**Fix 4 调整**:
```python
# 配置文件
detail_char_limit: 900  # 折中：从 1200 降到 900，不是 600
```

**预期效果**:
- Token 节省: -6,000/round (-43%)
- 提供足够的上下文信息
- Agent 能正常运行

---

## 🎯 推荐行动

### 立即执行

1. **回滚 Fix 2 的 Evidence 过滤**:
   ```python
   # src/game_agent/context/assembler.py
   # 恢复原始逻辑（只用数量限制，不过滤 confidence）
   verified = [item.to_dict() for item in self.evidence.verified()][-self.config.max_evidence_items:]
   active = [
       item.to_dict() for item in self.evidence.active()
       if item.status != EvidenceStatus.SUGGESTED
   ][-self.config.max_evidence_items:]
   suggested = [
       item.to_dict() for item in self.evidence.active()
       if item.status == EvidenceStatus.SUGGESTED
   ][: self.config.max_evidence_items]
   ```

2. **回滚 Fix 4 的配置修改**:
   ```json
   // configs/kitchen_chaos_optimized.json
   "detail_char_limit": 1200  // 恢复原值
   ```

3. **保留 Fix 1 和 Fix 3**:
   - exposure.py 的工具暴露优化
   - assembler.py 的验证摘要优化

### 验证测试

运行测试验证：
```powershell
.\scripts\verify_optimized_config.ps1 -RunCount 1
```

**成功标准**:
- ✅ 轮数 > 10（不是 2 轮）
- ✅ 退出原因不是早期 NoProgressExceeded
- ✅ Navigation precision > 0
- ✅ Token 每轮 < 12,000

---

## 📊 预期结果（方案 A）

### Before (原始)
- Avg tokens/round: 14,000
- 轮数: 7-9
- 退出: TotalTokenLimitExceeded

### After Fix (方案 A: 保守)
- Avg tokens/round: ~10,000 (-29%)
- 轮数: 15-18
- 退出: NoProgressExceeded (semantic, not token)
- **Token 节省**: ~4,000/round

### 节省来源
- Fix 1 (工具 Schema): -2,500
- Fix 3 (验证摘要): -1,400
- **Total**: -3,900 tokens/round

---

## 🔍 经验教训

### 1. 过度优化适得其反
- ✅ 减少无用overhead (tool schemas, 成功验证日志)
- ❌ 减少有用信息 (evidence, candidate details)
- **Balance is key**

### 2. 配置 vs 代码
- 配置值会覆盖代码默认值
- 需要同时更新配置文件和代码
- 测试时要确认实际生效的值

### 3. 渐进式优化
- 一次优化一个方面
- 每次测试验证效果
- 避免多个变量同时改变

### 4. Agent 行为敏感性
- Evidence 过滤影响 workflow 状态机
- Detail 不足影响 planning 质量
- **Context 质量 > Context 数量**

---

## ✅ 行动清单

- [ ] 回滚 Fix 2 (Evidence 过滤)
- [ ] 回滚 Fix 4 (detail_char_limit 600→1200)
- [ ] 保留 Fix 1 (工具 Schema 优化)
- [ ] 保留 Fix 3 (验证摘要优化)
- [ ] 运行验证测试
- [ ] 如果成功，更新文档
- [ ] 如果失败，考虑完全回滚所有修改

---

## 📝 结论

**当前状态**: ❌ Fix 过于激进，导致 agent 无法正常运行

**建议**: 
1. 立即回滚 Fix 2 和 Fix 4
2. 保留 Fix 1 和 Fix 3（这两个安全且有效）
3. 预期 token 节省 ~29%，同时保持 agent 功能正常

**关键洞察**:
- Token 优化不是"越少越好"
- 需要在效率和功能之间找到平衡
- 保守的优化 > 激进但会破坏功能的优化
