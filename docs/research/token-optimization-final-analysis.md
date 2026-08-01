# Token Optimization Test Results Comparison

## 📊 三次测试对比

### Run 1: 优化配置 + Fix 1-4（detail_char_limit=1200, Evidence有过滤）
- **轮数**: 15 轮
- **Total tokens**: 190,235 / 200,000 (95.1%)
- **Avg prompt tokens**: 10,239
- **退出**: `NoProgressExceeded` (卡在 DIAGNOSE)
- **问题**: 没进入 EXPLORE 阶段

### Run 2: 优化配置 + Fix 1-4（detail_char_limit=600, Evidence有过滤）
- **轮数**: 2 轮 ❌
- **Total tokens**: 12,507 / 200,000 (6.3%)
- **Avg prompt tokens**: 6,253
- **退出**: `NoProgressExceeded` (PLAN 阶段失败)
- **问题**: Detail 太小，无法规划

### Run 3: 优化配置 + Fix 1+3（detail_char_limit=1200, Evidence无过滤）
- **轮数**: 13 轮
- **Total tokens**: 190,287 / 200,000 (95.1%)
- **Avg prompt tokens**: 13,014 ⚠️
- **退出**: `TotalTokenLimitExceeded` ❌
- **问题**: Token 消耗反而更高了！

---

## 🔍 关键发现

### Evidence 过滤的影响

**有过滤（Run 1）**:
- Avg prompt tokens: **10,239**
- Evidence: 6+4+4 = 14 项

**无过滤（Run 3）**:
- Avg prompt tokens: **13,014** (+27%)
- Evidence: 最多 12+12+12 = 36 项

**结论**: Evidence 过滤虽然导致了功能问题，但确实节省了 ~3,000 tokens/round！

### Token 增长对比

| Round | Run 1 (有过滤) | Run 3 (无过滤) | 差异 |
|-------|---------------|---------------|------|
| 1 | 5,731 | 7,757 | +2,026 |
| 2 | 6,392 | 9,437 | +3,045 |
| 3 | 7,574 | 10,227 | +2,653 |
| 4 | 8,853 | 11,162 | +2,309 |
| 5 | 9,560 | 11,206 | +1,646 |
| 10 | 9,948 | 15,791 | +5,843 |
| 13 | 14,120 | 18,172 | +4,052 |

**平均差异**: ~3,000 tokens/round

---

## 💡 根本问题

### 矛盾困境

1. **Evidence 过滤 ON**: 
   - ✅ Token 节省 ~3,000/round
   - ❌ 功能受损（workflow 受阻）

2. **Evidence 过滤 OFF**:
   - ✅ 功能正常
   - ❌ Token 消耗高，仍会 TotalTokenLimitExceeded

### 真正的问题

**不是我们的 Fix 不好，而是基础配置有问题**:

```json
{
  "max_working_set_entries": 12,  // 工作集候选太多
  "max_evidence_items": 12,       // Evidence 上限太高
  "max_candidate_details": 3,     // Detail 太多
  "max_recent_messages": 3        // 保留消息太多
}
```

这些参数组合起来导致 context 过大：
- 12 evidence × 3 类 = 36 项
- 每项 ~200 tokens = 7,200 tokens
- 加上其他开销 = 10,000+ tokens/round

---

## 🎯 正确的解决方案

### 方案：调整配置参数（而非代码过滤）

**当前配置问题**:
```json
"max_evidence_items": 12  // 太多
```

**建议修改**:
```json
"max_evidence_items": 8   // 减少 33%
```

这样：
- Evidence: 8+8+8 = 24 项（vs 原来 36 项）
- 节省: ~2,400 tokens
- **不影响功能**（配置级别控制，不是代码过滤）

### 完整优化配置

```json
{
  "max_working_set_entries": 10,     // 从 12 降到 10
  "max_candidate_details": 2,         // 从 3 降到 2
  "max_recent_tool_results": 2,       // 保持不变
  "max_recent_messages": 2,           // 从 3 降到 2
  "detail_char_limit": 1000,          // 从 1200 降到 1000
  "tool_summary_char_limit": 800,     // 保持不变
  "max_evidence_items": 8,            // 从 12 降到 8
  "compression_trigger_ratio": 0.60,  // 从 0.65 降到 0.60（更早压缩）
  "working_set_detail_keep": 4        // 从 5 降到 4
}
```

**预期效果**:
- Evidence: -2,400 tokens (36→24 项)
- Details: -600 tokens (3→2 项，1200→1000 chars)
- Messages: -500 tokens (3→2 条)
- Working set: -1,000 tokens (12→10 项)
- **Total**: -4,500 tokens/round
- **New avg**: 13,000 → 8,500 tokens/round

---

## 📋 建议行动

### Option A: 调整配置（推荐）

1. 更新 `configs/kitchen_chaos_optimized.json` 的参数
2. 保留 Fix 1 和 Fix 3 的代码修改
3. **移除所有代码级别的过滤逻辑**

**优点**:
- 配置级别控制，清晰明确
- 不影响代码逻辑
- 更容易调试和调整

### Option B: 混合方案

1. 配置：适度减少（max_evidence_items: 10）
2. 代码：温和过滤（confidence > 0.7，而非 0.85）

**优点**:
- 双重保险
- 更精细的控制

**缺点**:
- 复杂度增加
- 难以调试

---

## 🎯 推荐的最终配置

### 配置文件更新

```json
{
  "context": {
    "enabled": true,
    "max_working_set_entries": 10,
    "max_candidate_details": 2,
    "max_recent_tool_results": 2,
    "max_recent_messages": 2,
    "detail_char_limit": 1000,
    "tool_summary_char_limit": 800,
    "compression_trigger_ratio": 0.60,
    "working_set_detail_keep": 4,
    "max_evidence_items": 8,
    "max_memory_items_per_field": 20,
    "max_durable_instruction_chars": 10000
  }
}
```

### 代码保留

- ✅ Fix 1: 工具 Schema 优化（exposure.py）
- ✅ Fix 3: 验证摘要优化（assembler.py）
- ❌ Fix 2: 移除（已回滚）
- ❌ Fix 4: 移除（已回滚）

---

## 📊 预期最终效果

### 配置优化 + Fix 1 + Fix 3

| 来源 | 节省 tokens |
|------|------------|
| Fix 1 (工具 Schema) | -2,500 |
| Fix 3 (验证摘要) | -1,400 |
| 配置调整 (evidence 12→8) | -2,400 |
| 配置调整 (details 3→2) | -600 |
| 配置调整 (messages 3→2) | -500 |
| 配置调整 (working_set 12→10) | -1,000 |
| 配置调整 (detail_char_limit 1200→1000) | -400 |
| **Total** | **-8,800 tokens/round** |

### 预期结果

- 当前 avg: 13,000 tokens/round
- 优化后: **4,200 tokens/round** (-68%)
- 轮数（200k）: 13 → **40+ 轮**
- 退出: TotalTokenLimitExceeded → Token 充足

---

## ✅ 结论

**关键洞察**: 
- 我们的代码修改方向是对的
- 但应该通过**配置**来控制，而非代码过滤
- 配置级别的限制不会破坏 agent 逻辑

**立即行动**:
1. 更新配置文件参数
2. 保留 Fix 1 和 Fix 3
3. 移除所有代码级别的 evidence 过滤
4. 重新测试
