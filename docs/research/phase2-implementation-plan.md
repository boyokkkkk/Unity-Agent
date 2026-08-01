# Phase 2 快速优化实施总结

## 执行时间
2026-08-01

---

## 已完成：冗余结构清理

### 优化 #1: Evidence 精简序列化 ✅

**文件**: `src/game_agent/context/models.py`

**修改**:
```python
# 新增方法
def to_context_dict(self) -> dict[str, Any]:
    """Minimal serialization for agent context."""
    return {
        "id": self.id,
        "claim": self.claim,
        "status": self.status.value,
        "sources": self.sources,
        "node_ids": self.node_ids,
    }
```

**应用**: `src/game_agent/context/assembler.py:628-636`
- 将 `item.to_dict()` 替换为 `item.to_context_dict()`
- 移除未使用字段：`confidence`, `created_at`, `updated_at`, `repository_revision`, `artifact_path`, `artifact_sha256`

**预期节省**: ~150 tokens/evidence × 20 items = **3,000 tokens**

---

### 优化 #2: Working Set 精简序列化 ✅

**文件**: `src/game_agent/context/assembler.py:637-648`

**修改**:
```python
working_refs = [
    {
        "id": entry.node_id,
        "kind": entry.kind,
        "name": entry.name,
        "path": entry.path,
        "status": entry.status,
        "evidence_ids": entry.evidence_ids,
        # 移除: "relevance": round(entry.relevance, 6),
    }
    for entry in self.working_set.entries.values()
]
```

**预期节省**: ~50 tokens/entry × 24 entries = **1,200 tokens**

---

### 优化 #3: Diagnosis Tool 描述精简 ✅

**文件**: `src/game_agent/aci/schemas.py:270-308`

**修改**:
- 删除 Example structure JSON（每个工具 ~8 行示例）
- 保留 REQUIRED FIELDS 说明
- 删除详细的参数示例（如 `e.g., ["C5"]`）

**预期节省**: ~300 tokens/tool × 2 tools = **600 tokens**

---

## 总节省估算

**立即生效**: ~4,800 tokens/round

**影响**:
- Context assembly 更简洁
- 减少模型处理负担
- 代码更易维护

---

## 待实施：Tool Lazy Loading

### 问题分析

**当前状况** (from Phase 1 test):
- Edit 阶段 tool schema: **19,242 tokens/call**
- 9 次 Edit 调用: **173k tokens** 浪费在 schema 上
- 占总 prompt 的 **62.5%**

**根本原因**:
- 14 个 ACI mutation 工具全部前置暴露
- 每个工具的详细 schema 都加载到 context

---

### Locus 方案借鉴

**Locus 工具加载机制**:

```typescript
// MCP Server Tools
{
  "loadMode": "lazy",  // vs "direct"
  "tools": [
    "unity_execute",
    "unity_hot_reload",
    // ... 60+ tools
  ]
}
```

**Meta-Tool 模式**:
```javascript
// Agent 首先调用 tool_load
tool_load("unity_script_patch")

// 然后才能调用实际工具
tool_call("unity_script_patch", {
  script_path: "...",
  old_text: "...",
  new_text: "..."
})
```

**关键优势**:
1. 初始 context 只包含 `tool_load` 和 `tool_call` 两个 meta-tool schema (~500 tokens)
2. 实际工具 schema 只在需要时加载
3. Agent 明确知道自己加载了哪些工具

---

### 实施方案

#### Step 1: 定义 Meta-Tools

**文件**: `src/game_agent/aci/schemas.py`

```python
META_TOOLS = [
    _tool(
        "tool_load",
        "Load a mutation tool schema on-demand before using it.",
        {
            "tool_name": {
                "type": "string",
                "enum": [
                    "unity_script_patch",
                    "unity_serialized_property_set",
                    "unity_component_add",
                    "unity_component_remove",
                    "unity_game_object_create",
                    "unity_game_object_delete",
                    "unity_game_object_rename",
                    "unity_prefab_create",
                    "unity_prefab_apply",
                    "unity_prefab_unpack",
                    "unity_asset_move",
                    "unity_asset_delete",
                    "unity_asset_save",
                    "code_diagnostics",
                ],
                "description": "Name of the mutation tool to load.",
            }
        },
        ["tool_name"],
    ),
    _tool(
        "tool_call",
        "Call a previously loaded mutation tool with arguments.",
        {
            "tool_name": {
                "type": "string",
                "description": "Name of the loaded tool to call.",
            },
            "arguments": {
                "type": "object",
                "description": "Tool-specific arguments as JSON object.",
            },
        },
        ["tool_name", "arguments"],
    ),
]
```

---

#### Step 2: 修改 Exposure 逻辑

**文件**: `src/game_agent/aci/exposure.py`

```python
def _workflow_exposure(phase: WorkflowPhase, ...) -> dict:
    """Dynamic tool exposure with lazy loading support."""
    
    if phase == WorkflowPhase.PLAN:
        # Plan 阶段只暴露 plan 工具
        return {
            "profile": "plan",
            "tool_names": ["task_plan_submit"],
            "tools": [tool for tool in ALL_TOOLS if tool["function"]["name"] == "task_plan_submit"],
        }
    
    if phase in [WorkflowPhase.EXPLORE, WorkflowPhase.INSPECT]:
        # 探索阶段：只读工具
        core_names = {
            "candidate_read",
            "unity_asset_search",
            "unity_ref_search",
            "unity_object_list",
            "unity_object_read",
            "unity_editor_status",
        }
        return {
            "profile": "explore" if phase == WorkflowPhase.EXPLORE else "inspect",
            "tool_names": list(core_names),
            "tools": [tool for tool in ALL_TOOLS if tool["function"]["name"] in core_names],
        }
    
    if phase == WorkflowPhase.DIAGNOSE:
        # 诊断阶段：只读 + 诊断工具
        diagnose_names = {
            "candidate_read",
            "unity_object_read",
            "diagnosis_submit",
            "diagnosis_revise",
        }
        return {
            "profile": "diagnose",
            "tool_names": list(diagnose_names),
            "tools": [tool for tool in ALL_TOOLS if tool["function"]["name"] in diagnose_names],
        }
    
    if phase == WorkflowPhase.EDIT:
        # 编辑阶段：META-TOOLS + 已加载的 mutations
        loaded_tools = context.get("loaded_tools", [])
        
        # 始终暴露 meta-tools
        exposed = META_TOOLS.copy()
        
        # 添加已加载的 mutation 工具
        for tool_name in loaded_tools:
            tool_schema = MUTATION_TOOLS_MAP.get(tool_name)
            if tool_schema:
                exposed.append(tool_schema)
        
        return {
            "profile": "edit",
            "tool_names": ["tool_load", "tool_call"] + loaded_tools,
            "tools": exposed,
        }
```

**关键变化**:
- Edit 阶段初始只暴露 `tool_load` 和 `tool_call`
- Agent 调用 `tool_load("unity_script_patch")` 后，该工具才进入 exposed tools
- 下一轮 context 才包含完整 schema

---

#### Step 3: 实现 Meta-Tool 处理逻辑

**文件**: `src/game_agent/aci/controller.py`

```python
def _execute_tool_load(self, tool_name: str) -> dict:
    """Handle tool_load meta-tool."""
    
    if tool_name not in MUTATION_TOOL_NAMES:
        return {
            "status": "error",
            "message": f"Unknown tool: {tool_name}. Available tools: {list(MUTATION_TOOL_NAMES)}",
        }
    
    # 添加到已加载工具列表
    if "loaded_tools" not in self._context_state:
        self._context_state["loaded_tools"] = []
    
    if tool_name not in self._context_state["loaded_tools"]:
        self._context_state["loaded_tools"].append(tool_name)
    
    # 返回工具的简要说明
    tool_schema = MUTATION_TOOLS_MAP[tool_name]
    
    return {
        "status": "ok",
        "message": f"Tool '{tool_name}' loaded successfully. You can now call it using tool_call.",
        "tool_description": tool_schema["function"]["description"],
        "required_parameters": tool_schema["function"]["parameters"]["required"],
    }


def _execute_tool_call(self, tool_name: str, arguments: dict) -> dict:
    """Handle tool_call meta-tool."""
    
    # 检查工具是否已加载
    loaded_tools = self._context_state.get("loaded_tools", [])
    if tool_name not in loaded_tools:
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' not loaded. Call tool_load('{tool_name}') first.",
        }
    
    # 委托给实际的 mutation 执行器
    return self._execute_mutation(tool_name, arguments)
```

---

#### Step 4: 更新 Agent Prompt

**文件**: `src/game_agent/framework/agents/default.py` (系统 prompt)

```markdown
## Tool Loading Strategy

In EDIT phase, mutation tools use lazy loading:

1. **Load before use**: Call `tool_load("tool_name")` to load a mutation tool
2. **Call the tool**: Use `tool_call("tool_name", {...})` with arguments
3. **Load only what you need**: Don't load all tools at once

Example workflow:
```
// Load script patching tool
tool_load("unity_script_patch")

// Use it
tool_call("unity_script_patch", {
  "script_path": "Assets/Scripts/Player.cs",
  "old_text": "...",
  "new_text": "..."
})
```

**Why**: Reduces context overhead from 19k to ~500 tokens initially.
```

---

### 预期效果

**Before** (当前):
- Edit 阶段初始 schema: 19,242 tokens
- 9 次调用: 173,178 tokens

**After** (lazy loading):
- Edit 阶段初始 schema: ~500 tokens (meta-tools only)
- 假设加载 3 个工具: 500 + (3 × 1,500) = 5,000 tokens
- 9 次调用: 5,000 tokens × 9 = 45,000 tokens

**节省**: 173k - 45k = **128,000 tokens** (~74% 减少)

---

### 实施步骤

1. ✅ **定义 META_TOOLS** (1 小时)
   - 在 schemas.py 中添加 tool_load 和 tool_call

2. **修改 Exposure 逻辑** (2 小时)
   - 更新 exposure.py 支持 lazy loading
   - 维护 loaded_tools 状态

3. **实现 Meta-Tool 处理** (3 小时)
   - 在 controller.py 添加 _execute_tool_load
   - 在 controller.py 添加 _execute_tool_call
   - 路由逻辑更新

4. **更新 Agent Prompt** (1 小时)
   - 指导 agent 使用 lazy loading 模式

5. **测试验证** (2 小时)
   - 单元测试
   - 集成测试（运行一次完整任务）

**总工作量**: 8-10 小时（1-2 个工作日）

---

## 下一步

**立即**:
1. 测试当前冗余清理的效果（运行一次任务）
2. 验证 token 节省是否达到预期

**本周**:
3. 实施 Tool Lazy Loading（最高优先级）
4. 实施 Knowledge Excerpt 模式

**预期总节省**:
- 冗余清理: ~4,800 tokens
- Tool Lazy Loading: ~128,000 tokens (Edit 阶段)
- Knowledge Excerpt: ~9,000 tokens
- **Total**: ~140k tokens (~50% 减少)

---

**文档创建时间**: 2026-08-01  
**状态**: 冗余清理完成，Tool Lazy Loading 待实施
