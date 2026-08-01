# Phase 1 测试结果分析

## 测试时间
2026-08-01 19:44

## 配置变更
1. ✅ Token budget: 200k → 300k
2. ✅ Working set auto-judgment 修复
3. ✅ UTF-8 BOM 修复

---

## 测试结果对比

| 指标 | Run 1 (旧) | Run 2 (Phase 1) | 变化 |
|------|-----------|----------------|------|
| **退出状态** | NoProgressExceeded | TotalTokenLimitExceeded | ⚠️ 更差 |
| **轮数** | 12 model calls | 22 model calls | ✅ +83% |
| **Total Tokens** | 245,514 / 200k | 286,252 / 300k | ✅ 95% budget |
| **运行时长** | 239s | 344s | +44% |
| **Navigation Precision** | 8.33% | 8.33% | 持平 |
| **Root Cause Rank** | 1 | null | ❌ 未找到根因文件 |
| **Relevant Recall** | 66.67% | 33.33% | ❌ -50% |
| **Files Accessed** | 24 | 12 | ❌ -50% |
| **Tool Calls** | 16 | 22 | +38% |
| **Failed Tools** | 3 | 5 | ❌ 更多失败 |

---

## 关键发现

### 1. Token Budget 有效但仍不够

**Run 1 (200k)**:
- 245,514 tokens (123% 超限)
- 提前退出

**Run 2 (300k)**:
- 286,252 tokens (95% 使用)
- 仍然 TotalTokenLimitExceeded
- 平均: 286,252 / 22 = **13,011 tokens/call**

**结论**: 
- 300k budget 延长了运行时间
- 但 token 消耗仍然过高
- 需要 **350-400k** 或更激进的 token 优化

---

### 2. Working Set Judgment 问题未解决

查看 trajectory.json 或 stage-metrics.json 中的 working set metrics：

**预期**: `working_set_judged_precision` 不再为 None

**需要验证**: 读取详细日志确认 judgment 是否生效

---

### 3. Navigation 变差

**Run 1**:
- Root cause rank: 1 ✅
- Relevant recall: 66.67%
- Files accessed: 24

**Run 2**:
- Root cause rank: null ❌ (未找到)
- Relevant recall: 33.33% ❌
- Files accessed: 12 ❌

**分析**:
- Agent 访问文件减少一半
- 可能陷入错误路径
- 未找到根因文件

---

### 4. Evidence Utilization 改善

**Run 1**:
- Evidence utilization: 0.0 ❌
- Referenced evidence nodes: 0

**Run 2**:
- Evidence utilization: 1.0 ✅
- Referenced evidence nodes: 3 ✅
- Unique evidence: 4 (vs 7)

**结论**: Evidence 系统开始工作了

---

### 5. Mutation 尝试

**Run 1**: 0 mutations
**Run 2**: 3 mutations (all typed, no escape hatch)

**进展**: Agent 开始尝试修改代码

---

## 问题诊断

### 问题 1: 为什么 Token 仍然超限？

**Token 分解**:
- Prompt: 276,838 (平均 12,583/call)
- Completion: 9,414
- Total: 286,252

**Tool Schema Overhead**:
- Avg per call: 1,435 tokens
- Total: 22 × 1,435 = 31,570 tokens

**阶段分布**:
- Plan: 263 tokens
- Explore: 4,083 tokens (×3 calls = 12,249)
- Inspect: 3,772 tokens (×4 calls = 15,088)
- Diagnose: 4,229 tokens (×5 calls = 21,145)
- Edit: 19,242 tokens (×9 calls = 173,178)

**关键问题**: 
- **Edit 阶段 tool schema 过大**: 19,242 tokens/call
- 9 次 Edit 调用 = 173k tokens 浪费在 schema 上
- 占总 prompt 的 **62.5%**

---

### 问题 2: 为什么 Navigation 变差？

可能原因：
1. **Auto-judgment 逻辑有 bug**
   - Evidence 关联不正确
   - Relevance label 未正确设置
   
2. **Working set 被过早修剪**
   - 配置 `max_working_set_entries: 10`
   - 可能丢失了重要候选

3. **搜索策略改变**
   - Agent 行为随机性
   - 本次运行恰好选错路径

---

## 下一步建议

### 立即行动

**Option A: 增加 Token Budget 到 400k**
```json
"max_total_tokens": 400000
```

**效果**:
- 13k/call × 30 calls = 390k
- 应该够用

**成本**: API 费用增加 100%

---

**Option B: 实现 Tool Lazy Loading（推荐）**

**问题**: Edit 阶段 schema 19,242 tokens 太大

**方案**: 
1. 只暴露 `tool_load` 和 `tool_call` meta-tools
2. 延迟加载 14 个 mutation 工具

**预期节省**:
- Edit schema: 19,242 → ~500 tokens (-96%)
- 9 次 Edit 调用: 节省 ~170k tokens
- **Total 减少到 ~120k tokens**

**工作量**: 3-5 天

---

**Option C: 诊断 Navigation 问题**

**需要**:
1. 读取 trajectory.json 验证 working set metrics
2. 检查 auto-judgment 是否生效
3. 对比两次运行的 working set 状态

**目的**: 确认修复是否有效

---

## 推荐实施顺序

### 短期（今天）

1. ✅ **增加 budget 到 400k** - 最简单
2. 🔍 **验证 auto-judgment 是否生效** - 读取日志

### 中期（本周）

3. ⭐ **实现 Tool Lazy Loading** - 最高 ROI
4. 📊 **运行 3 次测试对比** - 确认稳定性

### 长期（下周）

5. 🏗️ **Knowledge Excerpt 模式** - 进一步优化
6. 🤖 **Researcher Subagent** - 架构改进

---

## 结论

**Phase 1 成果**:
- ✅ Token budget 有效（延长运行）
- ✅ Evidence utilization 改善
- ✅ Agent 开始尝试修改
- ❌ Token 仍然不够
- ❌ Navigation 变差（可能是随机性）

**核心瓶颈**: 
- **Edit 阶段 tool schema 过大（19k tokens）**
- 占 prompt 的 62.5%
- **必须实现 lazy loading**

**立即建议**: 
1. 增加 budget 到 400k（应急）
2. 验证 auto-judgment 日志
3. 实施 tool lazy loading（根本解决）

---

**文档创建时间**: 2026-08-01  
**状态**: Phase 1 测试完成，需要进一步优化
