# Phase 2 测试诊断报告

## 测试信息
- 运行时间: 2026-08-01 20:09
- Run ID: optimized-run1-20260801-200921
- 配置: kitchen_chaos_optimized.json (300k budget)

---

## 关键发现

### ❌ Tool Lazy Loading 未生效

**证据**:
- Edit 阶段 tool schema: **22,352 tokens** (22 次调用)
- 平均 tool schema: **971 tokens/call**
- 对比 Phase 1: **19,242 tokens** (EDIT 单次)

**问题**:
- Meta-tools (tool_load, tool_call) 可能未被正确暴露
- 或者 Agent 不知道如何使用
- Edit 阶段调用了 22 次，但 schema 仍然很大

### ⚠️ Token 使用异常

**Total Tokens**: 294,909 / 300,000 (98% 使用)
- Prompt: 291,055 tokens
- Completion: 3,854 tokens

**异常**:
- Completion tokens 极低（只有 3,854）
- Model calls: 27 次
- Tool calls: **只有 7 次**（vs Phase 1 的 22 次）

**推断**: Agent 可能在早期遇到错误后反复重试，导致：
1. 大量 prompt tokens（每次重试都累积）
2. 极少的 completion tokens（错误后立即中断）
3. Tool calls 很少（没有成功执行实际工作）

### ✅ Phase 1 修复部分生效

**改善**:
- ✅ Root cause rank: 1 (vs Phase 1 Run 2 的 null)
- ✅ Relevant recall: 66.67% (vs 33.33%)
- ✅ Files accessed: 20 files (vs 12)
- ✅ Root cause MRR: 1.0

**问题**:
- ❌ Navigation precision: 6.9% (vs 8.33% 更差)
- ❌ Evidence utilization: 0.0 (vs Phase 1 Run 2 的 1.0)
- ❌ Working set size: 0 (非常异常)

### 🚨 严重问题：Working Set 为空

**发现**:
- `project-context-state.json` 显示 working set entries: **0**
- Conversation.jsonl 只有 **3 条消息**
- Agent 几乎立即退出

**推断**: 可能的致命错误
1. 初始化阶段崩溃
2. Tool exposure 配置错误
3. Meta-tools 导致格式错误

---

## Token 对比分析

| 指标 | Phase 1 Run 1 | Phase 1 Run 2 | Phase 2 | 预期 |
|------|--------------|--------------|---------|------|
| **Total Tokens** | 245,514 | 286,252 | 294,909 | ~230k |
| **Model Calls** | 12 | 22 | 27 | ~25 |
| **Tool Calls** | 16 | 22 | **7** | ~20 |
| **Completion** | 3,469 | 9,414 | **3,854** | ~8k |
| **Avg Prompt** | 20,459 | 12,583 | **10,780** | ~8k |
| **Tool Schema/call** | 2,116 | 1,435 | **971** | ~500 |
| **Exit Status** | NoProgress | TotalToken | TotalToken | Success |

**观察**:
1. ✅ 冗余清理生效：Avg tool schema 从 1,435 → 971 (-32%)
2. ❌ Lazy loading 未生效：Edit schema 仍然 22k tokens
3. ⚠️ Agent 行为异常：Tool calls 骤降，completion 极低

---

## 根本原因假设

### 假设 1: Meta-Tools 暴露问题

**症状**:
- Tool calls 只有 7 次（骤降 68%）
- Agent 可能不知道有哪些工具可用
- Edit 阶段 schema 仍然大

**验证**:
- 检查 conversation.jsonl 中的 tool_use 消息
- 查看 agent 是否尝试调用 tool_load
- 检查 exposure 日志

### 假设 2: 格式错误导致循环重试

**症状**:
- 27 model calls 但只有 7 tool calls
- Completion tokens 极低
- Working set 为空

**可能原因**:
- Meta-tools 的 schema 格式错误
- Agent 调用 meta-tools 时参数验证失败
- 每次失败后重新加载完整 context（累积 prompt tokens）

### 假设 3: select_agent_tools() 参数传递问题

**代码路径**:
```
controller.tool_exposure() 
  → select_tool_exposure(loaded_tools=self.loaded_tools)
    → _workflow_exposure(loaded_tools=...)
      → ToolExposure(tool_names=...)
        → model.set_available_tool_names(tool_names)
          → select_agent_tools(tool_names=..., loaded_mutation_tools=???)
```

**问题**: `loaded_mutation_tools` 参数可能未被传递到 `select_agent_tools()`

---

## 待验证检查点

### 1. 检查 Agent 看到的 Tools

```python
# 从 conversation.jsonl 第一条 assistant 消息中提取 tools
```

### 2. 检查 Meta-Tools 调用

```bash
# 在 conversation 中搜索 tool_load 或 tool_call
grep -i "tool_load\|tool_call" conversation.jsonl
```

### 3. 检查 Exposure 逻辑

```python
# 验证 _workflow_exposure 在 EDIT 阶段返回的 tool_names
```

### 4. 检查 select_agent_tools 调用

```python
# 在 litellm_model.py 中查找 select_agent_tools 的调用
# 验证 loaded_mutation_tools 参数是否传递
```

---

## 立即行动

### Option A: 回滚 Tool Lazy Loading，保留冗余清理

**原因**: Lazy loading 有 bug，导致 agent 无法正常工作

**步骤**:
1. 回滚 exposure.py 的 EDIT 阶段改动
2. 回滚 controller.py 的 meta-tool 处理
3. 保留冗余清理（Evidence, Working Set, Diagnosis）
4. 重新测试

**预期**: Token ~286k，但 agent 能正常工作

### Option B: 修复 Lazy Loading Bug

**需要**:
1. 读取 conversation.jsonl 确认 tools 列表
2. 找到 select_agent_tools 调用位置
3. 传递 loaded_mutation_tools 参数
4. 重新测试

**时间**: 1-2 小时

### Option C: 增加 Budget 到 400k（临时）

**同时**: 修复 Lazy Loading bug

**预期**: 争取时间完成修复

---

## 结论

**Phase 2 状态**:
1. ✅ 冗余清理生效（-32% tool schema）
2. ❌ Tool Lazy Loading 有严重 bug
3. ⚠️ Agent 行为异常，几乎无法工作

**建议**:
1. **立即**: 回滚 Lazy Loading，保留冗余清理
2. **短期**: 增加 budget 到 400k
3. **中期**: 修复 Lazy Loading，完成 Phase 2

**预期最终效果**（修复后）:
- 冗余清理: -4.8k tokens ✅
- Lazy Loading: -128k tokens (EDIT)
- Total: ~150k tokens（vs 当前 295k）

---

**文档创建时间**: 2026-08-01  
**状态**: Phase 2 测试失败，需要回滚或修复
