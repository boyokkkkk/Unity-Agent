# ACI Mutation执行问题修复报告

**日期：** 2026-08-02  
**问题：** Unity Script Patch执行失败  
**状态：** 🔧 已修复，测试中

---

## 🔍 问题诊断

### 问题现象

**日志：**
```
[INFO] coordinator: Generated 2 mutation(s)
[INFO] coordinator:   Action 1: ...
[INFO] coordinator:     File: Assets/Scripts/KitchenGameManager.cs
[INFO] coordinator:     Old text length: 157 chars
[INFO] coordinator:     New text length: 197 chars
[INFO] coordinator:   Executing action 1/2: unity_script_patch
[ERROR] coordinator:   Mutation failed: Unknown mutation error
```

**分析：**
- Decision成功生成完整mutation ✅
- Mutation格式验证通过 ✅
- 传递到MutationService ✅
- UnityMutationExecutor执行失败 ❌

### 根本原因

**缺少`expected_sha256`参数**

查看`src/game_agent_try/aci/mutation.py`的`_script_patch`方法：

```python
def _script_patch(self, args: dict[str, Any]) -> dict[str, Any]:
    path = args.get("path")
    old = args.get("old_text")
    new = args.get("new_text")
    expected = args.get("expected_sha256")  # 需要这个参数！
    
    # ... 使用expected_sha256进行验证
```

**问题：**
- Coordinator生成的action缺少`expected_sha256`字段
- UnityMutationExecutor需要这个字段来验证文件完整性
- 缺少时，执行失败并返回"Unknown mutation error"

**为什么需要expected_sha256？**
1. 验证文件自诊断后是否被修改
2. 确保old_text仍然在当前文件中
3. 安全机制，防止在过时的文件上应用补丁

---

## 🔧 应用的修复

### 修复1: 计算文件SHA256

**位置：** `src/game_agent_try/agents/coordinator.py` (第917-926行)

**修改：**

```python
try:
    with open(target_path, "r", encoding="utf-8") as f:
        file_content = f.read()

    # Calculate SHA256 for the file
    import hashlib
    file_sha256 = hashlib.sha256(file_content.encode("utf-8")).hexdigest()

except Exception as e:
    return {
        "success": False,
        "error": f"Failed to read target file: {e}",
    }
```

**改进：**
- ✅ 读取文件后立即计算SHA256
- ✅ 使用UTF-8编码确保一致性
- ✅ 添加到decision上下文

### 修复2: 在Action中包含SHA256

**位置：** `src/game_agent_try/agents/coordinator.py` (第1156-1165行)

**修改：**

```python
action = {
    "tool": "unity_script_patch",
    "arguments": {
        "path": mutation["file_path"],
        "old_text": mutation["old_text"],
        "new_text": mutation["new_text"],
        "expected_sha256": file_sha256,  # ✅ 添加SHA256
    },
    "authorized_paths": [mutation["file_path"]],
}
```

**改进：**
- ✅ 提供完整的参数给UnityMutationExecutor
- ✅ 满足安全验证要求
- ✅ 启用文件完整性检查

---

## 📊 修复前后对比

### 修复前

```
Coordinator生成action:
{
  "tool": "unity_script_patch",
  "arguments": {
    "path": "...",
    "old_text": "...",
    "new_text": "...",
    // ❌ 缺少 expected_sha256
  }
}

→ UnityMutationExecutor: 缺少required参数
→ 返回: "Unknown mutation error"
→ Mutations applied: 0
```

### 修复后

```
Coordinator生成action:
{
  "tool": "unity_script_patch",
  "arguments": {
    "path": "...",
    "old_text": "...",
    "new_text": "...",
    "expected_sha256": "abc123..."  // ✅ 包含SHA256
  }
}

→ UnityMutationExecutor: 验证参数完整
→ 验证文件SHA256匹配
→ 应用patch
→ 返回: success
→ Mutations applied: 1+
```

---

## 🎯 预期效果

### 场景1: 文件未修改（理想情况）

```
1. 计算文件SHA256: abc123...
2. Decision生成mutation with expected_sha256
3. UnityMutationExecutor验证:
   - 当前文件SHA256 == abc123... ✅
   - old_text在文件中存在 ✅
4. 直接应用patch
5. 返回success
```

### 场景2: 文件已修改（但old_text仍存在）

```
1. 计算文件SHA256: abc123...
2. Decision生成mutation
3. UnityMutationExecutor验证:
   - 当前文件SHA256 != abc123... ⚠️
   - old_text在当前文件中仍存在 ✅
4. 应用patch到当前内容
5. 返回success with warning
```

### 场景3: 文件已修改（old_text不存在）

```
1. 计算文件SHA256: abc123...
2. Decision生成mutation
3. UnityMutationExecutor验证:
   - 当前文件SHA256 != abc123... ⚠️
   - old_text在当前文件中不存在 ❌
4. 返回error: patch_failed
5. Coordinator回滚
```

---

## ✅ 验证方法

### 测试命令

```bash
cd E:\sysu-course\GameAgent
python scripts\test_real_task.py
```

### 成功标准

**必须达到：**
- ✅ Mutations applied > 0
- ✅ No "Unknown mutation error"
- ✅ Files changed > 0
- ✅ Clear success logs

**理想状态：**
- ✅ Mutations applied: 1-2
- ✅ Files changed: 1
- ✅ Validation passed
- ✅ Task completed successfully

### 关键日志

**成功时应该看到：**
```
[INFO] coordinator: Generated N mutation(s)
[INFO] coordinator:   Action 1: <description>
[INFO] coordinator:     File: <path>
[INFO] coordinator:     Old text length: XXX chars
[INFO] coordinator:     New text length: XXX chars
[INFO] coordinator:   Executing action 1/N: unity_script_patch
[INFO] mutation_service: Mutation succeeded  # ✅ 新的成功日志
[INFO] coordinator: Step 4: Running validation...
[INFO] coordinator: Validation passed!
```

**如果仍失败：**
```
[ERROR] coordinator:   Mutation failed: <详细错误>
```

---

## 🔄 回退计划

如果修复后仍然失败：

### Plan A: 检查文件路径

确保文件路径格式正确：
- 相对于project_root
- 使用正斜杠
- 不包含前导斜杠

### Plan B: 检查old_text匹配

确保old_text确实在文件中：
- 完全匹配（包括空格和换行）
- 检查编码问题
- 检查行尾符（CRLF vs LF）

### Plan C: 禁用SHA256验证（临时）

如果SHA256验证有问题：
- 传递空字符串或None
- 或修改UnityMutationExecutor跳过验证
- **仅用于调试，不推荐生产使用**

---

## 📈 修复影响

### Token使用

**不变：**
- Explorer: ~28k tokens
- Decision: ~5k tokens
- Total: ~33k tokens

**原因：** 只是添加SHA256计算，不改变LLM调用

### 成功率

**修复前：**
- 流程成功率: 100%
- Mutation执行率: 0%
- 整体成功率: 0%

**修复后（预期）：**
- 流程成功率: 100%
- Mutation执行率: 70-90%
- 整体成功率: 70-90%

### 系统可用性

**修复前：** MVP达标，但无法实际修改代码

**修复后：** 完全可用，可投入生产测试

---

## 📚 相关代码

### 修改的文件

1. **src/game_agent_try/agents/coordinator.py**
   - 第917-926行：添加SHA256计算
   - 第1156-1165行：在action中包含SHA256

### 相关的ACI代码

2. **src/game_agent_try/aci/mutation.py**
   - `_script_patch()` - 需要expected_sha256参数
   - 第238-334行：完整的patch逻辑

3. **src/game_agent_try/services/mutation_service.py**
   - `execute_mutation()` - 调用UnityMutationExecutor
   - 第69-112行：执行和结果处理

---

## 🎓 经验总结

### 问题定位过程

1. **第一层：** Mutation格式不完整 → 已修复
2. **第二层：** ACI执行失败 → 当前修复
3. **可能的第三层：** old_text不匹配？文件编码？

**教训：** 需要逐层剥离问题，每次只解决一个层次

### 接口契约的重要性

**问题根源：**
- Coordinator不知道UnityMutationExecutor需要expected_sha256
- 没有明确的接口文档
- 依赖隐式契约

**改进建议：**
1. 为ACI工具定义明确的接口契约
2. 在Coordinator层验证所有必需参数
3. 提供更好的错误信息（不是"Unknown error"）

### 安全机制的价值

**expected_sha256的作用：**
- ✅ 防止在过时文件上应用补丁
- ✅ 检测并发修改
- ✅ 提供诊断信息

**但也增加了复杂度：**
- 需要正确计算和传递
- 增加了失败的可能性
- 需要文档说明

---

## ✅ 修复确认清单

- [✅] 添加SHA256计算逻辑
- [✅] 在action中包含expected_sha256
- [✅] 使用正确的编码（UTF-8）
- [🧪] 运行真实任务测试
- [ ] 验证mutation成功执行
- [ ] 确认files changed > 0
- [ ] 验证validation通过

---

## 📝 后续行动

### 如果测试通过

1. ✅ 更新最终完成报告
2. ✅ 标记所有问题已解决
3. ✅ 系统投入生产就绪状态
4. ✅ 运行更多真实任务验证

### 如果测试仍失败

1. 检查详细的错误日志
2. 验证文件路径和编码
3. 检查old_text是否完全匹配
4. 考虑Plan A/B/C

### 长期改进

1. 改进错误信息（不要"Unknown error"）
2. 添加ACI接口文档
3. 实现mutation dry-run模式
4. 添加更多单元测试

---

**创建时间：** 2026-08-02  
**状态：** ACI修复已应用，测试运行中  
**预估测试时间：** 2-3分钟  
**信心水平：** 高（这是必需的参数）
