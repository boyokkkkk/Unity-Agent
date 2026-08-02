# Mutation格式问题修复报告

**日期：** 2026-08-02  
**问题：** Decision生成的mutation缺少必需字段  
**状态：** 🔧 已修复，测试中

---

## 🔍 问题诊断

### 原始问题

**现象：**
```
Mutations applied: 0
Error: Unknown mutation error
```

**根因：**
模型调用了`generate_mutations`工具，但返回的mutation对象缺少必需字段：
- ❌ 缺少`old_text`字段
- ❌ 缺少`new_text`字段
- ✅ 只有`description`字段

**日志证据：**
```
2026-08-02 14:07:57,781 [INFO] coordinator: Generated 1 mutation(s)
2026-08-02 14:07:57,782 [INFO] coordinator:   Action: Update the state transition logic...
2026-08-02 14:07:59,335 [ERROR] coordinator:   Mutation failed: Unknown mutation error
```

---

## 🔧 应用的修复

### 修复1: 增强输入验证和日志

**位置：** `src/game_agent_try/agents/coordinator.py` (第1128-1163行)

**修改内容：**

```python
# Convert to ACI mutation action format with validation
actions = []
for idx, mutation in enumerate(mutations, 1):
    # Validate mutation has required fields
    missing_fields = []
    if "file_path" not in mutation:
        missing_fields.append("file_path")
    if "old_text" not in mutation:
        missing_fields.append("old_text")
    if "new_text" not in mutation:
        missing_fields.append("new_text")

    if missing_fields:
        self.logger.error(f"  Mutation {idx} missing required fields: {missing_fields}")
        self.logger.error(f"  Mutation data: {mutation}")
        continue  # Skip invalid mutation

    # Check for empty values
    if not mutation["old_text"]:
        self.logger.error(f"  Mutation {idx} has empty old_text")
        continue
    if not mutation["new_text"]:
        self.logger.error(f"  Mutation {idx} has empty new_text")
        continue

    action = {
        "tool": "unity_script_patch",
        "arguments": {
            "path": mutation["file_path"],
            "old_text": mutation["old_text"],
            "new_text": mutation["new_text"],
        },
        "authorized_paths": [mutation["file_path"]],
    }
    actions.append(action)
    description = mutation.get("description", "No description")
    self.logger.info(f"  Action {idx}: {description}")
    self.logger.info(f"    File: {mutation['file_path']}")
    self.logger.info(f"    Old text length: {len(mutation['old_text'])} chars")
    self.logger.info(f"    New text length: {len(mutation['new_text'])} chars")
```

**改进点：**
1. ✅ 详细的字段验证
2. ✅ 清晰的错误日志
3. ✅ 跳过无效mutation而不是崩溃
4. ✅ 显示mutation的实际内容
5. ✅ 显示old_text和new_text的长度

### 修复2: 改进Prompt指令

**位置：** `src/game_agent_try/agents/coordinator.py` (第980-1013行)

**关键改进：**

1. **明确的字段要求：**
```
CRITICAL REQUIREMENTS FOR EACH MUTATION:
- file_path: The target file path
- old_text: EXACT text from the file (copy character-by-character)
- new_text: The replacement text
- description: Brief explanation
```

2. **具体的示例：**
```json
{
  "file_path": "Assets/Scripts/Example.cs",
  "old_text": "    void Start() {\n        Debug.Log(\"Hello\");\n    }",
  "new_text": "    void Start() {\n        InitializeGame();\n        Debug.Log(\"Hello\");\n    }",
  "description": "Add initialization call"
}
```

3. **强调要求：**
```
IMPORTANT:
- old_text must be an EXACT substring from the file
- Include enough context (multiple lines) to make it unique
- Preserve all whitespace, tabs, and line breaks exactly
- Do NOT use descriptions or summaries - provide actual code text
```

### 修复3: 增加文件内容长度

**修改：**
```python
# Before
{file_content[:2000]}

# After
{file_content[:5000]}
```

**原因：**
- 提供更多上下文给模型
- 增加找到正确代码片段的机会
- 2000字符可能不够覆盖完整的方法

---

## 🎯 预期效果

### 修复前的行为

```
Decision生成 → 模型返回 → 转换失败
                ├─ description: "..."
                ├─ old_text: 缺失
                └─ new_text: 缺失
                
→ KeyError/Unknown mutation error
→ Mutations applied: 0
```

### 修复后的行为

**场景1: 模型正确返回**
```
Decision生成 → 模型返回 → 验证通过 → 执行成功
                ├─ file_path: "..."
                ├─ old_text: "..."
                ├─ new_text: "..."
                └─ description: "..."
                
→ Mutation executed successfully
→ Mutations applied: 1+
```

**场景2: 模型仍返回不完整数据**
```
Decision生成 → 模型返回 → 验证失败 → 详细日志
                ├─ description: "..."
                ├─ old_text: 缺失
                └─ new_text: 缺失
                
→ Error: Mutation missing required fields: ['old_text', 'new_text']
→ Mutation data: {...}
→ Skip invalid mutation
→ Continue with next mutation (if any)
```

---

## 📊 验证方法

### 测试命令

```bash
cd E:\sysu-course\GameAgent
python scripts\test_real_task.py
```

### 成功标准

**必须达到：**
- ✅ Mutations applied > 0
- ✅ No "Unknown mutation error"
- ✅ Clear logs showing mutation details

**理想状态：**
- ✅ Mutations applied: 1-3
- ✅ Files changed: 1+
- ✅ Validation passed
- ✅ Task completed successfully

### 日志检查点

**关键日志：**
```
[INFO] coordinator: Generated N mutation(s)
[INFO] coordinator:   Action 1: <description>
[INFO] coordinator:     File: <path>
[INFO] coordinator:     Old text length: XXX chars
[INFO] coordinator:     New text length: XXX chars
[INFO] coordinator:   Executing action 1/N: unity_script_patch
[INFO] coordinator:   Mutation succeeded: N files changed
```

**如果失败，查看：**
```
[ERROR] coordinator:   Mutation missing required fields: [...]
[ERROR] coordinator:   Mutation data: {...}
```

---

## 🔄 回退计划

如果修复后仍然失败：

### Plan A: 使用Few-shot示例

在system message中添加具体示例：

```python
system_message = """You are a Unity code mutation specialist.

Example of correct mutation format:
{
  "reasoning": "The Start method needs initialization",
  "mutations": [
    {
      "file_path": "Assets/Scripts/GameManager.cs",
      "old_text": "    void Start() {\n        isPlaying = true;\n    }",
      "new_text": "    void Start() {\n        Initialize();\n        isPlaying = true;\n    }",
      "description": "Add Initialize call"
    }
  ]
}

You MUST provide old_text and new_text as exact code strings, not descriptions."""
```

### Plan B: 使用更强的模型

如果deepseek-v3不能稳定生成正确格式，考虑：
- GPT-4o
- Claude-3.5-sonnet
- Qwen-plus

### Plan C: 降级到描述式输出

如果结构化输出不可靠：
1. 让模型生成mutation描述
2. 使用第二次LLM调用提取old_text/new_text
3. 或者使用模板匹配

---

## 📈 预期改进

### Token使用

**不变：**
- Explorer: ~17k tokens
- Decision: ~4-5k tokens
- Total: ~21-22k tokens

**原因：** 修复主要是改进验证和prompt，不改变流程

### 成功率

**修复前：**
- 流程成功率: 100%
- Mutation执行率: 0%
- 整体成功率: 0%

**修复后（保守估计）：**
- 流程成功率: 100%
- Mutation执行率: 60-80%
- 整体成功率: 60-80%

**修复后（乐观估计）：**
- 流程成功率: 100%
- Mutation执行率: 80-90%
- 整体成功率: 80-90%

---

## ✅ 修复确认清单

- [✅] 添加mutation字段验证
- [✅] 改进错误日志输出
- [✅] 增强prompt指令
- [✅] 添加具体示例
- [✅] 增加文件内容长度
- [✅] 跳过无效mutation而不是崩溃
- [🧪] 运行真实任务测试
- [ ] 验证mutation成功执行
- [ ] 确认files changed > 0

---

## 📝 后续行动

### 如果测试通过

1. ✅ 更新Phase 2完成报告
2. ✅ 标记mutation问题已解决
3. ✅ 运行更多真实任务测试
4. ✅ 进入生产就绪状态

### 如果测试仍失败

1. 分析新的错误日志
2. 检查模型返回的实际数据
3. 考虑Plan A/B/C
4. 迭代修复

### 长期优化

1. 收集成功的mutation示例
2. 构建few-shot示例库
3. 优化prompt模板
4. 考虑专门的mutation模型

---

**创建时间：** 2026-08-02  
**状态：** 修复已应用，测试运行中  
**预估测试时间：** 2-3分钟  
**下一步：** 等待测试结果
