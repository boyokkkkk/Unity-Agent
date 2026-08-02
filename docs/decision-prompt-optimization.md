# Decision Prompt Optimization

## 概述

决策prompt是Coordinator将Explorer收集的证据转换为可执行mutation的关键环节。优化后的prompt能够：
1. 生成精确的old_text/new_text匹配
2. 减少幻觉和不准确的代码修改
3. 提高首次成功率
4. 减少回退和重试

## 当前实现

### 结构化输出Schema

```python
mutation_schema = {
    "type": "object",
    "properties": {
        "reasoning": {
            "type": "string",
            "description": "Brief explanation of why this mutation solves the task",
        },
        "mutations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["file_path", "old_text", "new_text", "description"],
            },
        },
    },
    "required": ["reasoning", "mutations"],
}
```

### Prompt模板要点

**关键指令：**
1. ✅ 提供完整文件内容（前2000字符）
2. ✅ 强调old_text必须精确匹配（包括空格/缩进）
3. ✅ 要求包含足够上下文使old_text唯一
4. ✅ 要求保持缩进和格式
5. ✅ 强调最小化更改

**输入上下文：**
- Task描述
- Top candidate（路径、角色、总结）
- 其他候选（2-3个）
- Evidence items（3条，前150字符）
- 文件内容预览（前2000字符）

## 优化建议

### 1. 增加Few-Shot示例

在prompt中添加好的和坏的mutation示例：

```python
GOOD_EXAMPLE = """
✅ GOOD Example:
Task: Add null check in ProcessInput method
old_text: '    void ProcessInput() {\n        player.Move(input);'
new_text: '    void ProcessInput() {\n        if (player == null) return;\n        player.Move(input);'
Description: Add null check before player access
```

```python
BAD_EXAMPLE = """
❌ BAD Example (Do NOT do this):
Task: Add null check
old_text: 'player.Move(input);'  # Too short, may match multiple places!
new_text: 'if (player != null) player.Move(input);'  # Changed indentation!
```

### 2. 分阶段决策（Two-Stage）

**Stage 1: 定位（Locate）**
- 输入：文件内容 + task
- 输出：具体的方法名/行号范围
- 目标：缩小修改范围

**Stage 2: 生成（Generate）**
- 输入：精确的代码片段（20-50行）
- 输出：exact old_text/new_text
- 目标：生成精确匹配

### 3. 上下文窗口优化

当前：提供前2000字符
优化：
- 如果Evidence包含行号信息 → 提取该行前后50行
- 如果Evidence包含方法名 → 提取整个方法
- 否则 → 提供前3000字符（增加覆盖）

### 4. 验证步骤

在生成mutation后，让LLM自我验证：

```python
verification_prompt = f"""
Verify this mutation is correct:

old_text: {old_text}
new_text: {new_text}

Questions:
1. Does old_text exist EXACTLY in the file? (including whitespace)
2. Is the context sufficient to make it unique?
3. Does new_text preserve indentation?
4. Is the change minimal?

Answer YES/NO for each question.
"""
```

### 5. 模型选择优化

**当前：** gpt-4o-mini（便宜但可能不够精确）

**优化策略：**
- Simple任务 → gpt-4o-mini（够用）
- Complex任务 → gpt-4o（更精确）
- High-risk任务 → gpt-4o + 额外验证

### 6. Temperature调优

**当前：** 0.3（中等随机性）

**建议：**
- Decision阶段：0.0（完全确定性，需要精确匹配）
- Exploration阶段：0.3（可以保持，允许创造性搜索）

## 实现优先级

### 🔥 高优先级（立即实现）
1. ✅ 结构化输出（已完成）
2. ✅ 文件内容提供（已完成）
3. ⚠️ Temperature降到0.0
4. ⚠️ 添加Few-Shot示例

### 📋 中优先级（Phase 1.5）
5. 分阶段决策（Locate → Generate）
6. 上下文窗口智能选择
7. 自我验证步骤

### 📊 低优先级（Phase 2）
8. 模型自适应选择
9. 多轮refinement
10. 成功率追踪和自动调优

## 测量指标

### 决策质量指标

1. **首次匹配率**（First Match Rate）
   - old_text能否在文件中找到
   - 目标：> 90%

2. **唯一匹配率**（Unique Match Rate）
   - old_text是否匹配多个位置
   - 目标：> 95%

3. **验证通过率**（Validation Pass Rate）
   - mutation后Unity能否编译
   - 目标：> 80%

4. **任务完成率**（Task Success Rate）
   - 最终是否解决了原始task
   - 目标：> 70%

### Token效率

- Decision tokens：目标 < 5k per decision
- 总token（Exploration + Decision）：目标 < 50k per task

## 测试用例

### 测试1：精确匹配
```python
Task: "Add null check in PlayerController.Update"
Expected: old_text包含完整的Update方法签名和至少3行代码
```

### 测试2：缩进保持
```python
Expected: new_text的缩进与old_text完全一致
```

### 测试3：最小化更改
```python
Expected: new_text只改变必要的行，不重写无关代码
```

## 下一步行动

1. ✅ **立即**：在`_make_mutation_decision`中将temperature设为0.0
2. ✅ **今天**：添加Few-Shot示例到prompt
3. **明天**：实现自我验证步骤
4. **本周**：收集50个真实任务，测量指标

---

**更新日期：** 2024-01-XX  
**状态：** Draft v1.0  
**负责人：** Phase 1 Team
