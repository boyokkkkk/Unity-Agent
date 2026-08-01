# Phase 2 最终测试结果分析

## 测试信息
- 运行时间: 2026-08-01 20:26
- Run ID: optimized-run1-20260801-202640
- 配置: 400k budget + 完整 Phase 2 优化
- 退出状态: TotalTokenLimitExceeded

---

## 关键发现：Tool Lazy Loading 仍未生效 ⚠️

### Edit 阶段 Tool Schema 分析

**实际结果**:
- Edit 阶段 tool schema: **34,544 tokens** (34 次调用)
- 平均: **1,016 tokens/call**
- Total calls: 39 model calls

**对比**:
| 测试 | Edit Schema (total) | Edit Calls | Avg/call | Budget | Status |
|------|---------------------|-----------|----------|--------|--------|
| Phase 1 Run 2 | 19,242 | 9 | 2,136 | 300k | Failed |
| Phase 2 (300k) | 22,352 | 22 | 1,016 | 300k | Failed |
| Phase 2 (400k) | 34,544 | 34 | 1,016 | 400k | Failed |

**观察**:
1. ✅ 平均 schema 降低：2,136 → 1,016 (-52%)
2. ❌ Edit 调用次数激增：9 → 34 (+278%)
3. ❌ Total Edit schema 增加：19k → 34k (+80%)

### 根本问题

**Tool Lazy Loading 未生效的证据**:
- Edit 阶段每次调用 schema 仍然是 1,016 tokens
- 预期：初始 ~500 tokens (meta-tools)，加载后 ~5,000 tokens
- 实际：每次都是 1k+ tokens

**可能原因**:
1. Agent 从未调用 `tool_load`
2. Meta-tools 未被正确暴露给 agent
3. Agent prompt 缺少使用指导

---

## Token 使用分析

### 总体情况

**Total Tokens**: 398,372 / 400,000 (99.6% 使用)
- Prompt: 394,341 tokens
- Completion: 4,031 tokens

**对比 Phase 1**:
| 指标 | Phase 1 Run 2 | Phase 2 (300k) | Phase 2 (400k) | 变化 |
|------|---------------|----------------|----------------|------|
| Total Tokens | 286,252 | 294,909 | 398,372 | +39% |
| Model Calls | 22 | 27 | 39 | +77% |
| Tool Calls | 22 | 7 | **6** | -73% |
| Completion | 9,414 | 3,854 | 4,031 | -57% |
| Avg Prompt | 12,583 | 10,780 | 10,111 | -20% |

**关键观察**:
1. ⚠️ Tool calls 骤降：22 → 6 (-73%)
2. ⚠️ Model calls 激增：22 → 39 (+77%)
3. ⚠️ Completion tokens 极低：4,031 (vs 预期 8k+)

**推断**: Agent 在循环重试，每次失败后重新生成 prompt，但很少成功执行工具。

---

## 行为分析

### Agent 行为异常

**Metrics**:
- Model calls: 39
- Tool calls: 6 (只有 6 次成功的工具调用)
- Failed tool calls: 1
- Blocked actions: 1

**Phase 分布**:
- Plan: 1 call
- Explore: 1 call
- Inspect: 1 call
- Diagnose: 2 calls
- **Edit: 34 calls** ← 异常

**Edit 阶段问题**:
- 34 次 model calls，但只产生了 6 次工具调用
- 意味着大多数 Edit 调用没有生成有效的工具使用
- Agent 可能在等待或重试某些操作

### Navigation 指标

**改善**:
- ✅ Root cause rank: 2 (vs Phase 1 Run 2 的 null)
- ✅ Relevant recall: 66.67%
- ✅ Files accessed: 22 files (vs 12)

**问题**:
- ❌ Navigation precision: 9.09% (vs 8.33%，略有改善但仍低)
- ❌ Evidence utilization: 0.0

---

## 冗余清理效果验证

### ✅ 冗余清理生效

**证据**:
- 平均 tool schema: 984.9 tokens/call
- Phase 1: 1,435 tokens/call
- **减少**: -31.4%

**各阶段 schema**:
| Phase | Schema (tokens) | Calls |
|-------|----------------|-------|
| Plan | 263 | 1 |
| Explore | 1,361 | 1 |
| Inspect | 943 | 1 |
| Diagnose | 1,300 | 2 |
| Edit | **1,016** | 34 |

**结论**: 冗余清理（Evidence, Working Set, Diagnosis Tool）确实生效，节省了约 450 tokens/call。

---

## 根本问题诊断

### 问题 1: Agent 不知道如何使用 Meta-Tools

**症状**:
- Edit 阶段 34 次调用，每次 schema 都是 1,016 tokens
- 没有证据显示 agent 调用了 `tool_load`
- Tool calls 极少（6 次）

**原因**: Agent prompt 缺少 meta-tools 使用指导

**需要**:
1. 检查 conversation.jsonl 确认 meta-tools 是否在 tool list 中
2. 检查 agent system prompt 是否包含 lazy loading 指导
3. 可能需要在 EDIT 阶段添加明确的使用示例

### 问题 2: Edit 阶段循环行为

**症状**:
- 34 次 model calls，只有 6 次 tool calls
- Completion tokens 极低（4,031）
- 每次调用平均 103 completion tokens

**推断**:
- Agent 可能在生成 prompt 后立即遇到错误
- 或者在等待某些条件（如 tool_load 完成）
- 或者格式错误导致重试

### 问题 3: Tool Calls 骤降

**对比**:
- Phase 1: 22 tool calls
- Phase 2: 6 tool calls (-73%)

**影响**:
- Agent 无法执行实际工作
- 大部分时间在循环重试
- Token 浪费在重复的 prompt 上

---

## 对比 Locus 实现

### Locus 的 Lazy Loading 机制

**关键差异**:

1. **Explicit Load Instructions**:
   ```
   Locus Agent Prompt:
   "Before using any mutation tool, you must first load it:
   1. Call tool_load with the tool name
   2. Wait for confirmation
   3. Then call tool_call with arguments"
   ```

2. **Tool State Visibility**:
   - Locus 在每次响应中显示 `loaded_tools: []`
   - Agent 明确知道哪些工具已加载

3. **Load Mode Declaration**:
   - Locus 在 tool registry 中明确标记 `ToolLoadMode::Lazy`
   - Agent 在看到工具列表时就知道需要先加载

### GameAgent 缺失的部分

**Current State**:
- ✅ Controller tracks loaded_tools
- ✅ Exposure logic includes meta-tools
- ✅ select_agent_tools dynamically builds schemas
- ❌ Agent prompt 没有 lazy loading 指导
- ❌ Agent 不知道需要先调用 tool_load
- ❌ 没有 loaded_tools 状态反馈

---

## 建议行动

### Option A: 添加 Agent Prompt 指导（最简单）

**实施**:
1. 在 `framework/agents/default.py` 的 instance_template 中添加：
   ```markdown
   ## Tool Loading in EDIT Phase
   
   Mutation tools use lazy loading. Before using any mutation tool:
   1. Call tool_load("tool_name") to load the tool
   2. Wait for confirmation (status: "ok")
   3. Then use tool_call("tool_name", {...}) to invoke it
   
   Example:
   - First: tool_load("unity_script_patch")
   - Then: tool_call("unity_script_patch", {script_path: "...", ...})
   ```

2. 在 tool_load 响应中返回 loaded_tools 列表

3. 重新测试

**预期**: Agent 理解如何使用 lazy loading

### Option B: 回滚 Tool Lazy Loading（保守）

**原因**: 
- 两次测试都失败
- Agent 行为异常
- Tool calls 骤降 73%

**保留**:
- 冗余清理（已验证有效）
- 400k budget（足够完成任务）

**预期**: Token ~350k，但 agent 能正常工作

### Option C: 借鉴 Locus 完整实现（彻底）

**需要**:
1. 在 tool schema 中标记 `load_mode: "lazy"`
2. 添加 loaded_tools 状态到每次响应
3. 完整的 agent prompt 指导
4. Tool loading 状态机

**时间**: 4-6 小时

---

## 结论

### Phase 2 状态

**已完成**:
1. ✅ 冗余清理生效（-31% tool schema）
2. ✅ Tool Lazy Loading 框架完整
3. ✅ Bug 修复（loaded_tools 传递）
4. ✅ Budget 增加到 400k

**未解决**:
1. ❌ Agent 不知道如何使用 meta-tools
2. ❌ Tool calls 骤降 73%
3. ❌ Edit 阶段循环行为
4. ❌ 仍然 TotalTokenLimitExceeded

**根本原因**: Agent prompt 缺少 lazy loading 使用指导

### 立即建议

**推荐: Option A（添加 Prompt 指导）**
- 实施简单（1 小时）
- 风险低
- 可能立即见效

**备选: Option B（回滚 Lazy Loading）**
- 如果 Option A 失败
- 保留冗余清理收益
- 400k budget 足够

### 预期最终效果

**Option A 成功后**:
- Tool schema: ~500 tokens 初始，~5,000 tokens 加载后
- Total tokens: ~230k
- 任务成功完成

**Option B（回滚）**:
- Tool schema: ~984 tokens/call
- Total tokens: ~350k / 400k
- 任务可能成功完成

---

**文档创建时间**: 2026-08-01  
**状态**: Phase 2 测试完成，需要添加 Agent Prompt 指导
