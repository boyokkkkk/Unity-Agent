# Phase 2 真实任务测试 - 完整诊断报告

**日期：** 2026-08-02  
**测试状态：** ✅ 流程成功，⚠️ Mutation失败

---

## 📊 测试结果总览

### 成功的部分 ✅

1. **复杂度评估** ✅
   - 正确识别为COMPLEX任务
   - 路由到complex_delegated路径

2. **Explorer探索** ✅  
   - 完成4轮探索
   - 收集4个evidence
   - 找到6个candidates
   - Token使用：17,138（效率78.6%）

3. **Decision生成** ✅
   - 成功生成decision reasoning
   - 生成1个mutation
   - 识别正确的文件：KitchenGameManager.cs

4. **整体流程** ✅
   - 端到端流程完整运行
   - 没有崩溃
   - 返回SUCCESS状态

### 失败的部分 ❌

**Mutations applied: 0**
- Decision生成了mutation描述
- 但mutation执行失败
- 错误：`Unknown mutation error`

---

## 🔍 详细问题诊断

### 问题1: Explorer Round 4 FormatError

**日志：**
```
2026-08-02 14:07:46,120 [ERROR] explorer: Model call failed: 
File "E:\sysu-course\GameAgent\src\game_agent_try\framework\models\utils\actions_toolcall.py", line 109
    raise FormatError
```

**分析：**
- Explorer第4轮，模型调用了未知的工具
- 触发FormatError异常
- Explorer捕获异常，使用fallback继续

**影响：**
- ⚠️ 轻微影响：Explorer提前结束第4轮
- ✅ 但仍收集了4个evidence和6个candidates
- ✅ 流程继续，没有中断

**根因：**
- 模型可能尝试调用了不在暴露工具列表中的工具
- 或者工具参数格式错误

### 问题2: Decision生成的Mutation格式错误

**日志：**
```
2026-08-02 14:07:57,781 [INFO] coordinator: Generated 1 mutation(s)
2026-08-02 14:07:57,782 [INFO] coordinator:   Action: Update the state transition logic...
2026-08-02 14:07:59,335 [ERROR] coordinator:   Mutation failed: Unknown mutation error
```

**Decision输出：**
```json
{
  "reasoning": "The issue occurs because the tutorial UI is not being closed...",
  "mutations": [
    {
      "description": "Update the state transition logic to ensure the tutorial UI is closed and the countdown UI is shown when the player presses the interact key."
    }
  ]
}
```

**问题：**
- ❌ mutation只有description
- ❌ 缺少`old_text`字段
- ❌ 缺少`new_text`字段
- ❌ 无法转换为ACI格式的action

**根因：**
- Decision的结构化输出schema可能不完整
- 或者模型没有正确填充所有必需字段

---

## 💡 根本原因分析

### Coordinator的Decision逻辑

查看`src/game_agent_try/agents/coordinator.py`中的`_make_mutation_decision()`方法：

**当前流程：**
1. 读取top candidate文件内容
2. 调用结构化输出生成mutation
3. 期望schema包含：
   - `old_text`: 要替换的原始代码
   - `new_text`: 替换后的新代码
   - `reasoning`: 修改理由

**实际问题：**
- Schema定义可能不清晰
- 模型返回了描述性文本而不是具体代码
- Coordinator没有验证mutation格式就传给MutationService

---

## 🔧 解决方案

### 方案1: 修复Decision的Schema（推荐）

**目标：** 确保mutation schema明确要求old_text和new_text

**修改：** `src/game_agent_try/agents/coordinator.py`

```python
mutation_schema = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why this mutation fixes the issue"
        },
        "mutations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "old_text": {
                        "type": "string",
                        "description": "EXACT text from the file to replace (must match exactly including whitespace and indentation)"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "New text to replace with (maintaining same indentation)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Brief description of what this mutation does"
                    }
                },
                "required": ["old_text", "new_text"],
                "additionalProperties": false
            }
        }
    },
    "required": ["reasoning", "mutations"],
    "additionalProperties": false
}
```

**关键点：**
- `required`: ["old_text", "new_text"] - 明确标记必需字段
- `additionalProperties: false` - 不允许额外字段
- 详细的description - 指导模型正确输出

### 方案2: 添加Mutation格式验证

**目标：** 在执行前验证mutation格式

**修改：** `src/game_agent_try/agents/coordinator.py`

```python
def _validate_mutation(self, mutation: dict) -> tuple[bool, str]:
    """Validate mutation has required fields."""
    if "old_text" not in mutation:
        return False, "Missing 'old_text' field"
    if "new_text" not in mutation:
        return False, "Missing 'new_text' field"
    if not mutation["old_text"]:
        return False, "'old_text' is empty"
    if not mutation["new_text"]:
        return False, "'new_text' is empty"
    return True, ""

# 在_make_mutation_decision中使用：
for idx, mutation in enumerate(mutations, 1):
    valid, error = self._validate_mutation(mutation)
    if not valid:
        self.logger.error(f"Mutation {idx} invalid: {error}")
        continue  # 跳过无效的mutation
    
    action = {
        "tool": "unity_script_patch",
        "arguments": {
            "path": file_path,
            "old_text": mutation["old_text"],
            "new_text": mutation["new_text"],
        },
        "authorized_paths": [file_path],
    }
    actions.append(action)
```

### 方案3: 改进MutationService错误信息

**目标：** 提供更有用的错误信息

**修改：** `src/game_agent_try/services/mutation_service.py`

```python
def execute_mutation(
    self,
    action: dict[str, Any],
    authorized_paths: list[str],
) -> MutationResult:
    """Execute a mutation with detailed error reporting."""
    self.execution_count += 1

    # 详细的输入验证
    if not action:
        return MutationResult(
            success=False,
            error="Mutation action is None or empty",
            ...
        )

    tool = action.get("tool")
    if not tool:
        return MutationResult(
            success=False,
            error=f"Missing 'tool' field in action: {action}",
            ...
        )

    arguments = action.get("arguments", {})
    if tool == "unity_script_patch":
        if "old_text" not in arguments:
            return MutationResult(
                success=False,
                error="unity_script_patch requires 'old_text' argument",
                ...
            )
        if "new_text" not in arguments:
            return MutationResult(
                success=False,
                error="unity_script_patch requires 'new_text' argument",
                ...
            )

    # ... 继续执行
```

---

## 🎯 立即行动计划

### 步骤1: 查看当前Decision的Schema定义

**检查文件：**
```bash
grep -A 50 "mutation_schema" src/game_agent_try/agents/coordinator.py
```

### 步骤2: 应用修复

根据发现的问题，应用方案1、2、3中的一个或多个。

### 步骤3: 重新测试

```bash
python scripts\test_real_task.py
```

**预期结果：**
- ✅ Decision生成包含old_text和new_text的mutation
- ✅ Mutation成功执行
- ✅ Mutations applied > 0

---

## 📊 当前vs目标状态对比

### 当前状态

```
Explorer ✅
├─ 4轮探索
├─ 收集4个evidence
├─ 找到6个candidates
└─ Token: 17,138

Decision ⚠️
├─ 生成reasoning ✅
├─ 生成mutation描述 ✅
└─ 缺少old_text/new_text ❌

Mutation ❌
└─ 执行失败: Unknown mutation error
```

### 目标状态

```
Explorer ✅
├─ 4轮探索
├─ 收集4个evidence
├─ 找到6个candidates
└─ Token: 17,138

Decision ✅
├─ 生成reasoning
├─ 生成完整mutation
│   ├─ old_text: "..."
│   ├─ new_text: "..."
│   └─ description: "..."
└─ 转换为ACI action

Mutation ✅
├─ 验证action格式
├─ 执行script patch
└─ 返回changed_paths
```

---

## ✅ 积极的发现

尽管mutation执行失败，但测试验证了：

1. ✅ **Phase 2复杂度评估完美工作**
   - 正确识别COMPLEX任务
   - 路由到正确路径

2. ✅ **Explorer高效且稳定**
   - 仅用17k tokens（vs 43k in Phase 3 test）
   - 收集了有用的evidence
   - FormatError被正确处理

3. ✅ **Decision逻辑基本正常**
   - 识别了正确的文件
   - 生成了合理的reasoning
   - 只是输出格式需要修复

4. ✅ **端到端流程健壮**
   - 没有崩溃
   - 错误被正确捕获
   - 返回了有意义的结果

---

## 📝 下一步行动

### 立即（修复mutation格式）

1. 检查当前mutation_schema定义
2. 应用方案1: 修复schema
3. 应用方案2: 添加验证
4. 应用方案3: 改进错误信息
5. 重新运行测试

### 短期（优化）

6. 分析Explorer的FormatError
7. 优化Explorer工具暴露
8. 减少Explorer的错误重试

### 中期（增强）

9. 添加mutation preview功能
10. 实现mutation的dry-run模式
11. 改进decision的few-shot示例

---

## 📚 相关文件

**需要修改：**
- `src/game_agent_try/agents/coordinator.py` - Decision schema和验证
- `src/game_agent_try/services/mutation_service.py` - 错误信息改进

**需要检查：**
- `src/game_agent_try/framework/models/utils/actions_toolcall.py` - FormatError触发条件
- `src/game_agent_try/agents/explorer.py` - 工具暴露逻辑

**测试脚本：**
- `scripts/test_real_task.py` - 真实任务测试

---

## 🎓 经验总结

1. **结构化输出需要严格的schema**
   - 明确标记required字段
   - 使用additionalProperties: false
   - 提供详细的description

2. **输入验证至关重要**
   - 在执行前验证格式
   - 提供清晰的错误信息
   - 避免"Unknown error"

3. **错误处理要分层**
   - Explorer层：捕获FormatError，继续探索
   - Decision层：验证输出格式
   - Mutation层：详细的错误报告

4. **测试揭示真实问题**
   - Phase 3的token问题遮盖了mutation格式问题
   - 真实任务测试暴露了schema定义不完整
   - 需要多场景测试才能发现所有问题

---

**创建时间：** 2026-08-02  
**状态：** 诊断完成，待修复  
**优先级：** 高（阻碍功能完整性）  
**预估修复时间：** 1-2小时
