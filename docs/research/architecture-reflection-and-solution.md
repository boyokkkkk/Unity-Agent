# GameAgent 架构反思与解决方案

## 执行时间
2026-08-01

---

## 📊 核心问题总结

### 问题 1: Token 消耗过高
- **现象**: 14,000 tokens/round → 只能运行 7-9 轮
- **目标**: 减少到 5,000 tokens/round
- **实际成果**: 优化后 11,707 tokens/round (-16%)
- **瓶颈**: 200k budget 不足，即使优化到 10k/round 也只能支持 20 轮

### 问题 2: 导航精度低（误解已澄清）
- **误解**: Navigation precision = 0.0
- **实际**: Navigation precision = 0.0909 (9.09%)
- **真正问题**: Working set judged precision = None（从未执行相关性判断）
- **根因**: Relevance judgment 机制未被触发

### 问题 3: 功能与效率的两难
- **激进优化** (Evidence过滤): 10,239 tokens/round 但功能受损
- **保守优化** (Config调整): 11,707 tokens/round 但仍超限
- **核心矛盾**: 减少 token 会损害 agent 功能

---

## 🔍 Locus vs GameAgent 架构对比

### 1. Context Assembly 策略

| 维度 | Locus | GameAgent | 差距 |
|------|-------|-----------|------|
| **Knowledge 注入** | L0/L1/L2 分层，excerpt 模式为默认 | 扁平结构，所有文档全量注入 | ❌ 缺少渐进式披露 |
| **Tool 暴露** | 延迟加载，meta-tool 分发 | 所有工具前置暴露 | ❌ Context 被 schema 膨胀 |
| **输出原则** | ~10 行简洁输出为默认 | 无限制 | ⚠️ 可能冗余 |
| **Git 状态** | 按需查询，不注入 | 未明确 | - |

**Locus 核心策略**:
```python
# Knowledge 分层
## L0 - 永远显示（一句话摘要）
## L1 - 默认折叠（关键规则）
## L2 - 完全折叠（详细示例）

# Tool 延迟加载
loadMode: "lazy"  # 工具不在初始 schema 中
tool_load("unity_execute")  # 显式加载
tool_call("unity_execute", {...})  # 调用
```

**GameAgent 当前**:
```python
# 所有 ACI mutation 工具前置暴露
# 预计 schema overhead: ~8-10k tokens
```

### 2. 搜索与导航机制

| 维度 | Locus | GameAgent | 差距 |
|------|-------|-----------|------|
| **语义搜索** | Roslyn 支持的 `code_symbol_search` | 仅 grep | ❌ 缺少语义级定位 |
| **引用追踪** | `code_find_references` 编译器级精度 | 基于 project_graph | ⚠️ 精度可能不足 |
| **Unity 资产** | `unity_asset_search` + IR 增量读取 | 完整文件读取 | ❌ 效率低 |
| **多模态策略** | 搜索 → 追踪 → 读取（分层） | 搜索 → 读取 | ⚠️ 缺少中间层 |
| **失败升级** | 无结果立即切换策略 | 可能重试相同方法 | ⚠️ 搜索预算浪费 |

**Locus Explorer 工作流**:
```
1. unity_asset_search (发现候选)
2. unity_ref_search (追踪依赖)
3. read (精准读取)
```

**GameAgent 当前工作流**:
```
1. project_graph_query (查询节点)
2. code_file_read (读取完整文件)
```

### 3. Subagent 架构

| 维度 | Locus | GameAgent | 差距 |
|------|-------|-----------|------|
| **专业化** | Dev/Explorer/Runtime 不同角色 | 单一 agent | ❌ 无角色分工 |
| **模型选择** | Explorer 用小模型（省 token） | 统一模型 | ❌ 成本高 |
| **委托模式** | 主 agent 委托研究任务给 Explorer | 无委托 | ❌ Context 污染 |
| **嵌套控制** | Depth=1, Concurrency=3 限制 | 无子 agent | - |

**Locus 委托示例**:
```python
# 主 agent 保持干净 context
task_create("explorer", "研究 UI 系统架构")

# Explorer 返回摘要（不污染主 context）
# 主 agent 只收到 summary，不包含中间过程
```

### 4. Knowledge & Memory 管理

| 维度 | Locus | GameAgent | 差距 |
|------|-------|-----------|------|
| **类型分类** | Design/Memory/Skill/Reference 4 层 | 无结构化 knowledge | ❌ 缺少分层 |
| **自动维护** | `/dream` 整合、去重、验证、清理 | 手动 | ❌ 无自动化 |
| **Skill 系统** | 可执行 SOP + 工具声明 + 验证流程 | Config-driven mutations | ⚠️ 不够灵活 |
| **Excerpt 模式** | 默认只显示摘要，需要时加载全文 | 全量加载 | ❌ Context 浪费 |

**Locus Skill 结构**:
```markdown
---
tools: [unity_execute, read, bash]
inject_mode: excerpt
---

## L0
简短摘要（永远显示）

## L1
核心规则（默认折叠）

## L2
详细示例（完全折叠）
```

---

## 🎯 根本问题诊断

### 导航问题真相

**误解**: Navigation precision = 0.0 导致任务失败

**实际**:
1. **Navigation precision = 9.09%** - 合理范围
2. **Working set judged precision = None** - 从未执行相关性判断
3. **Agent 能正常找到文件** - 在 15.6s 找到 `GameStartCountdownUI.cs`

**根因**: 
```python
# src/game_agent/context/models.py:226
judged = [...]  # 始终为空列表
"working_set_judged_precision": len(relevant) / len(judged) if judged else None
# → None (除以 0)
```

**影响**:
- Metrics 显示 0.0，但不影响实际功能
- Agent 能找到相关文件，能执行任务
- **导航问题与 token 优化无关**

### Token 优化的局限性

**已实施的优化**:
1. ✅ Fix 1: 工具 Schema 减少 (-2,500 tokens)
2. ✅ Fix 3: 验证摘要优化 (-1,400 tokens)
3. ✅ Config 参数调整 (-1,300 tokens)
4. **总计**: -5,200 tokens/round

**为什么不够**:
1. **其他开销未减少**:
   - Working set details: 仍然很大
   - Evidence 详情: 累积增长
   - Context 压缩: 不够激进

2. **累积效应**:
   - Round 1: 7,867 tokens
   - Round 15: 13,783 tokens ⬆ +75%
   - Compression 无法抑制增长

3. **200k Budget 根本不足**:
   - 即使优化到 10k/round，只支持 20 轮
   - 复杂任务需要 25-30 轮
   - **Budget 是瓶颈，不是效率**

---

## 💡 解决方案矩阵

### 短期方案（立即可行）

#### 方案 A: 增加 Token Budget（最简单）

**修改**:
```json
{
  "max_total_tokens": 300000  // 从 200k 增加
}
```

**效果**:
- 11,707 tokens/round × 25 轮 = 292,675 tokens
- ✅ 在 300k 内完成
- ✅ 无需修改代码
- ✅ 保持所有功能

**成本**: API 费用增加 50%

**推荐**: ⭐⭐⭐⭐⭐

---

#### 方案 B: 实现 Tool Lazy Loading（Locus 方案）

**修改**:
1. 创建 `tool_load` 和 `tool_call` meta-tools
2. 将 ACI mutations 标记为 lazy
3. 只暴露核心工具（read, grep, list）

**实现**:
```python
# src/game_agent/aci/exposure.py
def _lazy_tool_schema():
    return {
        "tool_load": {
            "description": "Load a tool schema on-demand",
            "parameters": {"tool_name": "string"}
        },
        "tool_call": {
            "description": "Call a loaded tool",
            "parameters": {"tool_name": "string", "args": "object"}
        }
    }

def select_tool_exposure(phase):
    if phase in [WorkflowPhase.PLAN, WorkflowPhase.EXPLORE]:
        return _lazy_tool_schema() + core_tools
    else:
        return _lazy_tool_schema() + loaded_tools
```

**效果**:
- 初始 schema: ~3-4k tokens（减少 60%）
- 按需加载 mutations
- **预计节省**: -4,000 tokens/round

**工作量**: 3-5 天

**推荐**: ⭐⭐⭐⭐

---

#### 方案 C: 添加 Researcher Subagent

**修改**:
1. 创建 `researcher` subagent（只读工具）
2. 委托 EXPLORE 任务给 researcher
3. 主 agent 只接收摘要报告

**实现**:
```python
# configs/researcher_agent.json
{
  "tools": ["code_file_read", "grep", "project_graph_query"],
  "model": "qwen-turbo",  # 小模型
  "max_output_tokens": 1024
}

# src/game_agent/aci/workflow.py
def _explore_phase(self):
    if self.working_set.size() == 0:
        # 委托给 researcher
        summary = self.delegate_subagent(
            "researcher",
            "找到实现 state-event baseline 相关的文件"
        )
        self.observe_research_complete(summary)
```

**效果**:
- 主 agent context 不包含探索细节
- 小模型处理搜索（成本降低 80%）
- **预计节省**: -3,000 tokens/round (主 agent)

**工作量**: 5-7 天

**推荐**: ⭐⭐⭐⭐

---

### 中期方案（1-2 周）

#### 方案 D: Knowledge Excerpt 模式

**修改**:
1. 为每个 skill/reference 添加 L0/L1/L2 分层
2. 默认只注入 L0（一句话摘要）
3. 按需加载 L1/L2 详情

**示例**:
```markdown
# skill/unity_script_patch.md

## L0
修改 C# 脚本，支持 evidence-based old_text 验证

## L1
### 参数
- script_path: 脚本路径
- old_text: 原始代码片段
- new_text: 新代码
- evidence_id: 关联的 evidence ID

## L2
### 详细示例
[长示例代码...]
```

**效果**:
- Skill 文档从 ~500 tokens 减少到 ~50 tokens
- 20 个 skills × 450 tokens = **-9,000 tokens**

**工作量**: 3-5 天

**推荐**: ⭐⭐⭐⭐⭐

---

#### 方案 E: 语义代码搜索（Locus 方案）

**修改**:
1. 集成 Roslyn 或 tree-sitter
2. 实现 `code_symbol_search`（语义级）
3. 实现 `code_find_references`（编译器级）

**工具对比**:
```python
# 当前 grep（文本级）
grep("public.*Player", "*.cs")
→ 找到 100+ 匹配，很多误报

# Roslyn 语义搜索
code_symbol_search("Player", type="class")
→ 精确找到 3 个 Player 类定义
```

**效果**:
- Navigation precision 从 9% 提升到 40-60%
- 减少无效文件读取
- **预计节省**: -2,000 tokens/round

**工作量**: 1-2 周

**推荐**: ⭐⭐⭐⭐

---

### 长期方案（2-4 周）

#### 方案 F: 完整 Skill 系统

**设计**:
```
skills/
  mutation-recovery/
    skill.md          # L0/L1/L2 分层文档
    scripts/
      diagnose.py     # 诊断脚本
      recover.py      # 恢复脚本
    tests/
      test_recovery.py
  state-event-baseline/
    skill.md
    scripts/
      implement.py
```

**Skill 文档格式**:
```markdown
---
tools: [unity_script_patch, code_diagnostics]
inject_mode: excerpt
maintainer: ai
---

## L0
实现 state-event baseline observability

## L1
### 流程
1. 定位 UI 状态变化点
2. 添加 event 触发逻辑
3. 验证事件链完整性

### 工具
- unity_script_patch: 修改脚本
- unity_execute: 运行验证代码

## L2
### 完整示例
[...]
```

**效果**:
- 可复用的任务模板
- 验证流程嵌入 skill
- **预计节省**: -5,000 tokens/round

**工作量**: 2-3 周

**推荐**: ⭐⭐⭐⭐⭐

---

#### 方案 G: Memory 自动整合

**实现** `/dream` 命令:
```python
# src/game_agent/skills/dream.py
def consolidate_memory():
    """
    1. 读取所有 memory 文档
    2. 识别重复和矛盾
    3. 合并相似条目
    4. 删除过期信息
    5. 验证与当前代码库一致性
    """
    memories = load_all_memories()
    
    # 去重
    deduplicated = deduplicate_by_similarity(memories, threshold=0.85)
    
    # 验证
    for mem in deduplicated:
        if not verify_against_codebase(mem):
            mark_as_stale(mem)
    
    # 限制数量
    keep_top_n(deduplicated, n=20)
```

**效果**:
- 自动清理过期 memory
- 减少冗余信息
- **预计节省**: -1,000 tokens/round

**工作量**: 1 周

**推荐**: ⭐⭐⭐

---

## 📋 推荐实施路线图

### Phase 1: 立即行动（1 天）

1. ✅ **增加 Token Budget 到 300k**
   - 修改 `configs/kitchen_chaos_optimized.json`
   - 验证测试 3 次
   - 预期完成率: 80-90%

2. ✅ **修复 Working Set Judged Precision**
   - 实现自动相关性判断
   - 位置: `src/game_agent/context/models.py`
   - 消除 metrics 中的 None 值

### Phase 2: 快速优化（3-5 天）

3. ⭐ **实现 Knowledge Excerpt 模式**
   - 为所有 skills 添加 L0/L1/L2
   - 节省 ~9,000 tokens
   - 最高 ROI

4. ⭐ **实现 Tool Lazy Loading**
   - 创建 meta-tool 架构
   - 延迟加载 mutations
   - 节省 ~4,000 tokens

### Phase 3: 架构改进（1-2 周）

5. **添加 Researcher Subagent**
   - 分离探索和实现职责
   - 小模型处理搜索
   - 节省 ~3,000 tokens + 成本

6. **集成语义代码搜索**
   - Roslyn 或 tree-sitter
   - 提升 navigation precision
   - 减少无效读取

### Phase 4: 完整 Skill 系统（2-4 周）

7. **构建 Skill Package**
   - 可执行 SOP 模板
   - 验证流程嵌入
   - 长期可维护性

8. **Memory 自动整合**
   - `/dream` 命令
   - 自动去重和验证
   - 长期稳定性

---

## 🎯 最终建议

### 核心洞察

1. **Token 优化已达合理水平**
   - 16% 改善不错
   - 继续优化会损害功能
   - **Budget 是瓶颈**

2. **导航问题是独立问题**
   - 与 token 优化无关
   - 实际 precision 是 9.09%，可接受
   - 需要独立修复 judgment 机制

3. **架构差距明显**
   - Locus 在 context 管理上领先 2-3 代
   - 需要系统性借鉴，而非局部修补
   - **渐进式披露是核心原则**

### 行动优先级

**立即** (今天):
1. 增加 token budget 到 300k
2. 修复 working set judged precision 计算

**本周**:
3. 实现 knowledge excerpt 模式（最高 ROI）
4. 实现 tool lazy loading

**下周**:
5. 添加 researcher subagent
6. 集成语义代码搜索

**本月**:
7. 构建完整 skill 系统
8. 实现 memory 自动整合

### 预期效果

**Phase 1 后**:
- 11,707 tokens/round × 25 轮 = 292k ✅
- 任务完成率: 80-90% ⬆
- 成本增加: 50%

**Phase 2 后**:
- ~8,000 tokens/round (-32% 进一步优化)
- 300k budget 支持 37 轮
- 成本增加: 25%（相比原始）

**Phase 3-4 后**:
- ~6,000 tokens/round (-48% 总优化)
- 300k budget 支持 50 轮
- 成本增加: 0%（与原始持平）
- 功能: 显著增强（语义搜索、subagent）

---

## ✅ 结论

**当前状态**: 陷入两难 - token 高 vs 功能完整性

**根本原因**: 架构设计缺少渐进式披露原则

**解决路径**: 
1. 短期增加 budget（解燃眉之急）
2. 中期借鉴 Locus 架构（excerpt、lazy load）
3. 长期重构为 skill 系统（可维护性）

**不建议**: 
- ❌ 继续配置级优化（收益递减）
- ❌ 回滚所有优化（浪费已有成果）
- ❌ 一味减少 token（损害功能）

**推荐**: 
- ✅ 架构层面反思和重构
- ✅ 借鉴 Locus 的成熟方案
- ✅ 渐进式实施（每步可验证）

---

**文档创建时间**: 2026-08-01  
**状态**: 待执行 Phase 1
