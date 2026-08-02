# Phase 1 后续实施清单

## ✅ 已完成（今天）

- [x] Action格式转换实现
- [x] Simple任务执行路径
- [x] High-risk路径 + Critic
- [x] 决策Prompt优化文档
- [x] 完整测试套件

**状态：Phase 1 核心功能 100% 完成** ✅

---

## 🎯 立即可做（优先级排序）

### Priority 1: 快速优化（30分钟）

1. **降低Decision的Temperature**
   ```python
   # 位置: src/game_agent_try/agents/coordinator.py
   # 在 _make_mutation_decision() 中：
   structured_model = StructuredOutputModel(
       base_model=self.model,
       schema=mutation_schema,
       temperature=0.0,  # 添加这行，当前是继承model的0.3
   )
   ```

2. **添加Few-Shot示例到Decision Prompt**
   ```python
   # 在 decision_prompt 中添加：
   GOOD_EXAMPLE = """
   Example of GOOD mutation:
   old_text: '    void Update() {\n        player.Move();'
   new_text: '    void Update() {\n        if (player != null) player.Move();'
   ✓ Exact match, includes context, preserves indentation
   """
   ```

### Priority 2: 测试准备（30分钟）

3. **配置API密钥**
   ```bash
   # 在 .env 文件或环境变量中设置
   export OPENAI_API_KEY="sk-..."
   ```

4. **验证测试环境**
   ```bash
   cd E:\sysu-course\GameAgent
   python -c "from game_agent_try.agents.coordinator import CoordinatorAgent; print('OK')"
   ```

5. **选择测试任务**
   创建 `tests/test_tasks.txt`：
   ```
   # Simple任务（3个）
   1. Add a debug log in KitchenGameManager.cs
   2. Add null check in PlayerController.cs Update method
   3. Add comment to GameManager.cs Start method

   # Complex任务（5个）
   4. Find the GameStateManager and add initialization logging
   5. Find where player input is processed and add validation
   6. Locate the scoring system and add boundary checks
   7. Find the UI manager and add null safety
   8. Locate spawn logic and add error handling
   ```

### Priority 3: 首次测试（1-2小时）

6. **手动运行测试**
   ```python
   # 创建简单测试脚本 tests/run_manual_test.py
   from pathlib import Path
   from game_agent_try.agents.coordinator import CoordinatorAgent
   from game_agent_try.context import ContextAssembler
   from game_agent_try.framework.models.litellm_model import LitellmModel

   project_root = Path(r"E:\sysu-course\SeriousGame")
   context = ContextAssembler(project_root=project_root)
   model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
   coordinator = CoordinatorAgent(model=model, context=context, project_root=project_root)

   task = "Add a debug log in KitchenGameManager.cs"
   result = coordinator.run_task(task)
   
   print(f"Success: {result.get('success')}")
   print(f"Path: {result.get('path')}")
   print(f"Error: {result.get('error', 'None')}")
   ```

7. **记录结果**
   创建 `test_results.md` 记录每个任务的：
   - 成功/失败
   - 执行路径（simple/complex/high-risk）
   - Token消耗
   - 失败原因（如果失败）

---

## 📋 本周目标

### Day 1-2: 快速验证
- [ ] 运行10个测试任务
- [ ] 识别主要问题
- [ ] 快速修复blocker

### Day 3-4: Prompt优化
- [ ] 根据失败案例优化prompt
- [ ] 调整文件上下文策略
- [ ] 测试优化效果

### Day 5: 数据分析
- [ ] 统计成功率
- [ ] 分析token消耗
- [ ] 生成Phase 1.5报告

---

## 🐛 可能遇到的问题

### 问题1: old_text匹配失败
**原因：** LLM生成的text不精确
**解决：**
- ✅ 降低temperature到0.0
- ✅ 提供更多文件上下文
- 增加Few-Shot示例

### 问题2: 文件路径提取失败
**原因：** 正则表达式覆盖不全
**解决：**
- 扩展 `_extract_file_path()` 的pattern列表
- 添加模糊匹配（搜索相似文件名）
- 回退到Complex路径

### 问题3: Validation失败
**原因：** 生成的代码有语法错误
**解决：**
- 增强prompt中的"preserve syntax"指令
- 添加代码语法检查
- 实现多轮refinement

### 问题4: Token消耗过高
**原因：** 文件内容太长
**解决：**
- 限制文件预览到关键部分
- 使用Evidence中的行号信息定位
- 实现智能上下文窗口

---

## 📊 成功指标

### MVP目标（第一批10个任务）

| 指标 | 目标 | 测量方法 |
|------|------|---------|
| 整体成功率 | > 50% | 完成任务 / 总任务 |
| Simple路径成功率 | > 70% | Simple成功 / Simple总数 |
| Token效率 | < 50k avg | 平均token / 任务 |
| 首次匹配率 | > 60% | old_text找到 / 总mutations |

### Phase 1.5目标（50个任务后）

| 指标 | 目标 |
|------|------|
| 整体成功率 | > 70% |
| 验证通过率 | > 80% |
| 平均执行时间 | < 2分钟 |

---

## 🔧 快速参考

### 运行单个任务
```python
result = coordinator.run_task("your task here")
```

### 查看日志
```python
import logging
logging.basicConfig(level=logging.INFO)
```

### 检查Token消耗
```python
print(f"Exploration tokens: {result.get('exploration_tokens', 0)}")
print(f"Total metrics: {result.get('metrics')}")
```

### 查看生成的Actions
```python
# 在 _make_mutation_decision() 返回前添加：
for action in actions:
    print(f"Action: {action}")
```

---

## 📚 相关文档

- **架构说明：** `docs/phase1-optimization-summary.md`
- **Prompt优化：** `docs/decision-prompt-optimization.md`
- **测试套件：** `tests/test_coordinator_complete.py`
- **原始报告：** `docs/phase1-final-report.md`

---

## 💡 最后提醒

1. **先小规模测试** - 不要一次运行50个任务
2. **记录失败案例** - 这是优化的宝贵数据
3. **Token预算注意** - 如果API有限额，先测5个
4. **及时调整** - 发现问题立即修复，不等批量测试完

---

**现在的系统已经可以运行真实任务了！祝测试顺利！** 🚀

**需要帮助时：**
- 查看 `docs/decision-prompt-optimization.md` 了解优化方向
- 检查 coordinator.py 中的日志输出
- 分析失败的 old_text/new_text 找pattern

Good luck! 💪
