# Phase 1 真实任务测试方案

## 📋 发现的真实任务

**任务描述：**
```
玩家在开始界面按下交互键后，游戏应进入倒计时；
目前教程界面没有关闭，倒计时界面也没有出现。
问题可能位于游戏状态切换与 UI 刷新链路。
请定位根因，进行最小修复，并通过相关 Unity 测试验证。
```

**项目信息：**
- 项目路径：`E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos`
- Unity版本：2021.3.45f1c1
- 任务类型：游戏状态切换 + UI刷新bug修复

---

## 🎯 任务分析

### 任务复杂度评估

**复杂度：COMPLEX** ✅

理由：
1. ❌ 没有明确的文件路径（需要搜索）
2. ✅ 需要理解游戏状态机制
3. ✅ 涉及多个系统（状态管理 + UI）
4. ✅ 需要找到状态切换逻辑

**预期执行路径：** Complex Delegated（Explorer + Decision + Execute）

### 涉及的系统

1. **游戏状态管理**
   - 状态切换逻辑
   - 教程 → 倒计时状态转换

2. **UI系统**
   - 教程界面关闭
   - 倒计时界面显示

3. **输入处理**
   - 交互键响应
   - 状态触发

---

## ✅ 当前架构适配性分析

### Phase 1系统能力 vs 任务需求

| 需求 | Phase 1能力 | 状态 |
|------|------------|------|
| 搜索相关代码 | ✅ Explorer Agent | 适配 |
| 理解游戏状态 | ✅ Evidence收集 | 适配 |
| 找到UI管理器 | ✅ 图查询工具 | 适配 |
| 生成修复代码 | ✅ Action转换 | 适配 |
| 执行mutation | ✅ MutationService | 适配 |
| 验证修复 | ✅ ValidationService | 适配 |

**结论：完全适配！** ✅

### 预期执行流程

```
1. Coordinator评估复杂度 → COMPLEX
   ↓
2. 委托Explorer搜索：
   - "game state manager"
   - "tutorial UI"
   - "countdown UI"
   - "state transition"
   ↓
3. Explorer收集Evidence：
   - GameStateManager.cs（状态管理）
   - TutorialUI.cs（教程界面）
   - CountdownUI.cs（倒计时界面）
   - 状态切换方法
   ↓
4. Coordinator决策：
   - 分析状态切换逻辑
   - 识别缺失的UI关闭/显示调用
   - 生成修复mutation
   ↓
5. MutationService执行：
   - 修改状态切换方法
   - 添加UI刷新调用
   ↓
6. ValidationService验证：
   - Compile通过
   - EditMode测试通过
   - PlayMode测试通过
```

---

## 🔧 适配调整（备份原任务）

### 步骤1: 创建测试配置（备份）

<function_calls>
<invoke name="Write">
<parameter name="content"># Phase 1 Test Configuration (Backup of kitchen_chaos.json)

**原始配置：** `configs/kitchen_chaos.json`  
**备份位置：** `configs/kitchen_chaos_backup.json`  
**Phase 1配置：** `configs/phase1_test.json`

---

## 创建Phase 1测试配置

```json
{
  "task": "玩家在开始界面按下交互键后，游戏应进入倒计时；目前教程界面没有关闭，倒计时界面也没有出现。问题可能位于游戏状态切换与 UI 刷新链路。请定位根因，进行最小修复，并通过相关 Unity 测试验证。",
  "project_root": "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos",
  "unity_editor": "D:/unity/unity editor/2021.3.45f1c1/Editor/Unity.exe",
  "expected_complexity": "COMPLEX",
  "expected_path": "complex_delegated",
  "test_mode": "phase1_validation"
}
```

---

## 测试方案

### 方案A: 使用现有Coordinator直接测试（推荐）

```python
from pathlib import Path
from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel

# 初始化
project_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")
context = ContextAssembler(project_root=project_root)
model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
coordinator = CoordinatorAgent(
    model=model,
    context=context,
    project_root=project_root,
)

# 真实任务
task = """玩家在开始界面按下交互键后，游戏应进入倒计时；
目前教程界面没有关闭，倒计时界面也没有出现。
问题可能位于游戏状态切换与 UI 刷新链路。
请定位根因，进行最小修复，并通过相关 Unity 测试验证。"""

# 运行
result = coordinator.run_task(task)

# 分析结果
print(f"Success: {result['success']}")
print(f"Path: {result['path']}")
print(f"Exploration tokens: {result.get('exploration_tokens', 0)}")
print(f"Evidence count: {result.get('evidence_count', 0)}")
print(f"Mutations applied: {result.get('mutations_applied', 0)}")
```

### 方案B: 集成到baseline命令（需要适配）

需要创建一个wrapper，将Coordinator集成到现有的baseline流程中。

---

## 预期结果

### Token消耗预期

- Explorer搜索：~30k-40k tokens（5-6轮）
- Decision生成：~8k tokens
- **总计：~40k-50k tokens**
- **vs Baseline：~80k tokens（节省40%）** ✅

### 时间预期

- Explorer：~60-90秒
- Decision：~15秒
- Mutation：~5秒
- Validation：~30秒
- **总计：~110-140秒（约2分钟）**

### 成功指标

| 指标 | 目标值 | 测量 |
|------|--------|------|
| 找到正确文件 | ✅ | 检查candidate_nodes |
| 生成可执行action | ✅ | 检查actions不为空 |
| Mutation成功 | ✅ | 检查mutation_results |
| Validation通过 | ⚠️ | 可能失败（首次尝试）|
| 任务完成 | 📊 | 需手动验证游戏 |

**首次成功率预期：50-70%**

---

## 潜在问题和解决方案

### 问题1: 文件路径提取失败

**原因：** 中文任务描述，没有明确文件名

**解决：** ✅ 已支持，会走Complex路径使用Explorer搜索

### 问题2: 搜索关键词不精确

**原因：** LLM可能选择不当的搜索词

**解决：** 
- Explorer会自适应调整搜索词
- 多轮探索覆盖不同角度

### 问题3: 修复可能不完整

**原因：** 可能只修了UI显示，没修状态切换

**解决：**
- Decision prompt强调"最小修复"
- 如果validation失败，可以手动分析并调整

### 问题4: Validation可能失败

**原因：** 生成的代码有语法错误或逻辑问题

**解决：**
- 有自动回滚机制
- 可以分析失败原因后重试
- 或手动微调生成的mutation

---

## 测试检查清单

### 前置检查

- [ ] OpenAI API Key已设置
- [ ] Unity项目路径正确：`E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos`
- [ ] Unity Editor路径正确：`D:\unity\unity editor\2021.3.45f1c1\Editor\Unity.exe`
- [ ] 项目图已生成
- [ ] Context可以正常加载

### 执行中监控

- [ ] Coordinator正确评估为COMPLEX
- [ ] Explorer启动并开始搜索
- [ ] 收集到相关Evidence（> 3个）
- [ ] 找到候选文件（> 5个）
- [ ] Decision生成了actions（不为空）
- [ ] Mutation执行成功
- [ ] Validation运行（即使失败也要记录）

### 结果分析

- [ ] 记录所有metrics（tokens, 时间, 文件）
- [ ] 保存生成的actions内容
- [ ] 分析失败原因（如果失败）
- [ ] 检查changed_paths是否合理
- [ ] 手动运行游戏验证修复

---

## 快速启动命令

```python
# 保存为 scripts/test_real_task.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from game_agent_try.agents.coordinator import CoordinatorAgent
from game_agent_try.context import ContextAssembler
from game_agent_try.framework.models.litellm_model import LitellmModel
import json
import logging

logging.basicConfig(level=logging.INFO)

# 配置
project_root = Path(r"E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos")
task = """玩家在开始界面按下交互键后，游戏应进入倒计时；
目前教程界面没有关闭，倒计时界面也没有出现。
问题可能位于游戏状态切换与 UI 刷新链路。
请定位根因，进行最小修复，并通过相关 Unity 测试验证。"""

# 初始化
context = ContextAssembler(project_root=project_root)
model = LitellmModel(model_name="gpt-4o-mini", temperature=0.3)
coordinator = CoordinatorAgent(model=model, context=context, project_root=project_root)

# 运行
print("\n" + "="*80)
print("Phase 1 Real Task Test - Kitchen Chaos State Transition Bug")
print("="*80)
print(f"\nTask: {task}\n")

result = coordinator.run_task(task)

# 保存结果
output_file = "artifacts/phase1_real_task_result.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("\n" + "="*80)
print("Result Summary")
print("="*80)
print(f"Success: {result['success']}")
print(f"Path: {result['path']}")
print(f"Exploration tokens: {result.get('exploration_tokens', 'N/A')}")
print(f"Evidence count: {result.get('evidence_count', 'N/A')}")
print(f"Mutations applied: {result.get('mutations_applied', 'N/A')}")
print(f"\nFull result saved to: {output_file}")
print("="*80)
```

运行：
```bash
cd E:\sysu-course\GameAgent
python scripts/test_real_task.py
```

---

## 下一步

1. **立即测试**：运行上述脚本
2. **记录结果**：保存所有metrics和日志
3. **分析问题**：如果失败，分析根因
4. **迭代优化**：根据结果调整prompt或策略
5. **对比baseline**：与原baseline系统对比效果

**预期：这是Phase 1的毕业考试！** 🎓
