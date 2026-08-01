# Tool Lazy Loading - 完整实施指南

## 已完成

### 1. Meta-Tools 定义 ✅
**文件**: `src/game_agent/aci/schemas.py`

```python
# 已添加
META_TOOLS = [
    _tool("tool_load", ...),
    _tool("tool_call", ...),
]
META_TOOL_NAMES = frozenset(...)
MUTATION_TOOLS_MAP = {tool["function"]["name"]: tool for tool in TYPED_MUTATION_TOOLS}
```

### 2. Exposure 逻辑更新 ✅
**文件**: `src/game_agent/aci/exposure.py`

- 导入 META_TOOLS, META_TOOL_NAMES, MUTATION_TOOLS_MAP
- `_workflow_exposure()` 增加 `loaded_tools` 参数
- EDIT 阶段只暴露 meta-tools + loaded_tools

---

## 待实施

### 3. Controller 状态管理

**文件**: `src/game_agent/aci/controller.py`

**需要添加**:

```python
class ACIController:
    def __init__(self, ...):
        # 现有初始化...
        self.loaded_tools: set[str] = set()  # 跟踪已加载的工具
    
    def _reset_for_new_task(self):
        """新任务开始时重置状态"""
        self.loaded_tools.clear()
```

---

### 4. Meta-Tool 处理逻辑

**文件**: `src/game_agent/aci/controller.py`

**位置**: 在 `execute()` 方法中添加路由

```python
def execute(self, tool_name: str, arguments: dict) -> dict:
    """Execute ACI tool with lazy loading support."""
    
    # Meta-tool 路由
    if tool_name == "tool_load":
        return self._execute_tool_load(arguments.get("tool_name", ""))
    
    if tool_name == "tool_call":
        inner_tool_name = arguments.get("tool_name", "")
        inner_arguments = arguments.get("arguments", {})
        return self._execute_tool_call(inner_tool_name, inner_arguments)
    
    # 现有工具执行逻辑...
    if tool_name in QUERY_TOOL_NAMES:
        return self._execute_query(tool_name, arguments)
    # ...
```

**新增方法 #1**: `_execute_tool_load()`

```python
def _execute_tool_load(self, tool_name: str) -> dict:
    """Handle tool_load meta-tool."""
    from .schemas import MUTATION_TOOL_NAMES, MUTATION_TOOLS_MAP
    
    # 验证工具名称
    if not tool_name:
        return {
            "status": "error",
            "message": "tool_name is required",
        }
    
    if tool_name not in MUTATION_TOOL_NAMES:
        available = sorted(MUTATION_TOOL_NAMES)
        return {
            "status": "error",
            "message": f"Unknown tool: {tool_name}",
            "available_tools": available,
        }
    
    # 添加到已加载列表
    if tool_name not in self.loaded_tools:
        self.loaded_tools.add(tool_name)
        load_status = "loaded"
    else:
        load_status = "already_loaded"
    
    # 返回工具的简要说明
    tool_schema = MUTATION_TOOLS_MAP[tool_name]
    required_params = tool_schema["function"]["parameters"].get("required", [])
    
    return {
        "status": "ok",
        "load_status": load_status,
        "tool_name": tool_name,
        "message": f"Tool '{tool_name}' is now available. Use tool_call to invoke it.",
        "description": tool_schema["function"]["description"],
        "required_parameters": required_params,
        "loaded_tools": sorted(self.loaded_tools),
    }
```

**新增方法 #2**: `_execute_tool_call()`

```python
def _execute_tool_call(self, tool_name: str, arguments: dict) -> dict:
    """Handle tool_call meta-tool."""
    from .schemas import MUTATION_TOOL_NAMES
    
    # 验证工具是否已加载
    if tool_name not in self.loaded_tools:
        return {
            "status": "error",
            "message": f"Tool '{tool_name}' not loaded. Call tool_load('{tool_name}') first.",
            "loaded_tools": sorted(self.loaded_tools),
        }
    
    # 验证工具名称有效
    if tool_name not in MUTATION_TOOL_NAMES:
        return {
            "status": "error",
            "message": f"Invalid tool name: {tool_name}",
        }
    
    # 委托给实际的 mutation 执行器
    try:
        return self._execute_mutation(tool_name, arguments)
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error executing {tool_name}: {str(e)}",
            "tool_name": tool_name,
        }
```

---

### 5. Exposure 调用更新

**文件**: `src/game_agent/aci/controller.py`

**位置**: 在调用 `select_tool_exposure()` 的地方传递 `loaded_tools`

```python
# 找到类似这样的调用
exposure = select_tool_exposure(
    phase=...,
    unresolved_slot_ids=...,
    working_paths=...,
    pending_stage=...,
    workflow=...,
)

# 更新为
exposure = select_tool_exposure(
    phase=...,
    unresolved_slot_ids=...,
    working_paths=...,
    pending_stage=...,
    workflow=...,
    loaded_tools=self.loaded_tools,  # 新增参数
)
```

**需要更新 exposure.py 中的函数签名**:

```python
def select_tool_exposure(
    *,
    phase: str,
    unresolved_slot_ids: Iterable[str],
    working_paths: Iterable[str],
    pending_stage: str = "",
    enabled: bool = True,
    workflow: WorkflowState | None = None,
    loaded_tools: set[str] | None = None,  # 新增参数
) -> ToolExposure:
    # ...
    if workflow is not None:
        return _workflow_exposure(
            workflow, 
            working_paths, 
            pending_stage=pending_stage,
            loaded_tools=loaded_tools,  # 传递给 _workflow_exposure
        )
```

---

### 6. Tool Schema 构建更新

**文件**: `src/game_agent/framework/agents/default.py` 或 tool exposure 相关代码

**问题**: 当前代码从 `ACI_TOOLS` 列表获取所有工具 schema

**需要**: 动态构建 schema，只包含暴露的工具

```python
def _build_tool_schemas(self, exposed_tool_names: set[str]) -> list[dict]:
    """Build tool schemas for exposed tools, including loaded mutations."""
    from game_agent.aci.schemas import (
        ACI_TOOLS,
        META_TOOLS,
        MUTATION_TOOLS_MAP,
    )
    
    schemas = []
    
    # 添加非 mutation 工具
    for tool in ACI_TOOLS:
        tool_name = tool["function"]["name"]
        if tool_name in exposed_tool_names:
            # 如果是 mutation 但未加载，跳过
            if tool_name in MUTATION_TOOLS_MAP and tool_name not in self.controller.loaded_tools:
                continue
            schemas.append(tool)
    
    # 添加 meta-tools（如果在 exposed 中）
    for tool in META_TOOLS:
        if tool["function"]["name"] in exposed_tool_names:
            schemas.append(tool)
    
    # 添加已加载的 mutation 工具（动态）
    for tool_name in self.controller.loaded_tools:
        if tool_name in MUTATION_TOOLS_MAP:
            schemas.append(MUTATION_TOOLS_MAP[tool_name])
    
    return schemas
```

---

### 7. Agent Prompt 更新

**文件**: System prompt 或 agent instructions

**添加到 EDIT 阶段说明**:

```markdown
## Tool Loading Strategy

Mutation tools use **lazy loading** in EDIT phase:

### How to use:

1. **Load the tool first**:
   ```json
   {
     "tool_name": "tool_load",
     "arguments": {
       "tool_name": "unity_script_patch"
     }
   }
   ```

2. **Then call it**:
   ```json
   {
     "tool_name": "tool_call",
     "arguments": {
       "tool_name": "unity_script_patch",
       "arguments": {
         "script_path": "Assets/Scripts/Player.cs",
         "old_text": "void Start() {}",
         "new_text": "void Start() { Debug.Log(\"Hello\"); }"
       }
     }
   }
   ```

### Available mutation tools:
- unity_script_patch
- unity_serialized_property_set
- unity_component_add
- unity_component_remove
- unity_gameobject_create
- unity_gameobject_delete
- unity_gameobject_rename
- unity_prefab_create
- unity_asset_save
- code_diagnostics
- (etc.)

### Best practices:
- Load only the tools you need
- tool_load returns the required parameters
- Check loaded_tools in tool_load response
```

---

## 测试计划

### 单元测试

**文件**: `tests/test_aci_lazy_loading.py`

```python
def test_tool_load_success():
    controller = ACIController(...)
    result = controller.execute("tool_load", {"tool_name": "unity_script_patch"})
    assert result["status"] == "ok"
    assert "unity_script_patch" in controller.loaded_tools

def test_tool_load_invalid():
    controller = ACIController(...)
    result = controller.execute("tool_load", {"tool_name": "invalid_tool"})
    assert result["status"] == "error"

def test_tool_call_not_loaded():
    controller = ACIController(...)
    result = controller.execute("tool_call", {
        "tool_name": "unity_script_patch",
        "arguments": {}
    })
    assert result["status"] == "error"
    assert "not loaded" in result["message"]

def test_tool_call_after_load():
    controller = ACIController(...)
    controller.execute("tool_load", {"tool_name": "unity_script_patch"})
    result = controller.execute("tool_call", {
        "tool_name": "unity_script_patch",
        "arguments": {
            "script_path": "test.cs",
            "old_text": "old",
            "new_text": "new",
            "evidence_node_ids": []
        }
    })
    # 应该委托给实际的 mutation 执行
```

### 集成测试

运行一次完整的 baseline 测试，验证：
1. Agent 能正确调用 tool_load
2. Agent 能正确调用 tool_call
3. Token 使用显著降低
4. 任务能够正常完成

---

## 预期效果

### Token 节省

**Before** (当前 Phase 1):
```
EDIT 阶段 tool schema: 19,242 tokens/call
9 次 EDIT 调用: 173,178 tokens
```

**After** (lazy loading):
```
初始 meta-tools schema: ~500 tokens
加载 3 个工具后: 500 + (3 × 1,500) = 5,000 tokens
9 次 EDIT 调用: 45,000 tokens
```

**节省**: 173k - 45k = **128,000 tokens** (~74% 减少)

### Context 使用

**Before**:
- 平均 13k tokens/call
- 300k budget 支持 23 calls

**After**:
- 平均 ~8k tokens/call
- 300k budget 支持 37 calls
- 或者 200k budget 支持 25 calls ✅

---

## 实施步骤总结

1. ✅ 定义 META_TOOLS（已完成）
2. ✅ 更新 exposure.py（已完成）
3. ⏳ Controller 状态管理（待实施）
4. ⏳ Meta-tool 处理逻辑（待实施）
5. ⏳ Exposure 调用更新（待实施）
6. ⏳ Tool schema 动态构建（待实施）
7. ⏳ Agent prompt 更新（待实施）
8. ⏳ 测试（待实施）

**预计剩余工作量**: 4-6 小时

---

**文档创建时间**: 2026-08-01  
**状态**: 部分完成，核心逻辑待实施
