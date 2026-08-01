# 测试现状分析与消融实验建议

## 当前测试现状

### 1. 单元测试
**文件**: `tests/test_*.py` (15个测试文件)

**覆盖范围**:
- ✅ `test_aci.py` - ACI核心逻辑
- ✅ `test_aci_mutation.py` - Mutation执行
- ✅ `test_aci_workflow.py` - Workflow状态机
- ✅ `test_evidence_artifact_p0.py` - P0 Evidence Artifact (我们添加的)
- ✅ `test_evidence_artifact_p0_simple.py` - P0简化测试
- ✅ `test_context.py` - Context管理
- ✅ `test_project_graph.py` - Project graph
- ✅ `test_framework.py` - Framework基础
- ✅ `test_baseline.py` - Baseline runner
- ✅ `test_baseline_e2e.py` - E2E fixture测试

**特点**:
- 覆盖了大部分核心组件
- 有P0的单元测试
- 有fixture-based的E2E测试（不需要真实Unity）

---

### 2. 真实E2E测试任务

**当前唯一的真实任务**: Kitchen Chaos `state-event-v1`

**来源**: `configs/kitchen_chaos.json` + baseline runner

**任务描述**:
```
玩家在开始界面按下交互键后，游戏应该进入倒计时；
目前教程界面没有关闭，倒计时界面也没有出现。
问题可能位于游戏状态切换与 UI 刷新链路。
```

**特点**:
- ✅ 真实Unity项目（Kitchen Chaos）
- ✅ 需要修改C#代码
- ✅ 需要运行Unity测试验证
- ✅ 有完整的validation流程
- ✅ 涉及多个文件（GameInput, KitchenGameManager, UI组件）
- ✅ 测试state-machine、cross-file、UI等多个维度

---

### 3. 潜在的其他任务

**发现**: `configs/localization.kitchen-chaos.json` 包含**10个定位任务**

**任务列表**:
1. `state-event-start-countdown` - 状态事件和倒计时（我们用的这个）
2. `stove-progress-burn-warning` - 炉灶进度条和烧焦警告
3. `delivery-result-ui` - 配送结果UI
4. `player-movement-animation-sound` - 玩家移动动画音效
5. `cutting-counter-progress` - 切菜台进度
6. `plates-counter-stack` - 盘子堆叠
7. `plate-ingredient-visuals` - 盘子食材可视化
8. `container-counter-spawn-visual` - 容器台生成可视化
9. `pause-options-rebind` - 暂停选项重绑定
10. `audio-volume-options` - 音频音量选项

**覆盖的维度**:
- State machine
- UI交互
- Animation
- Audio
- Prefab操作
- SerializedProperty修改
- Event系统
- Unity Event

**但是**: 这些是**定位任务**（localization），不是**修复任务**（fix defect）

---

## 消融实验的测试需求分析

### 问题：是否需要更多测试任务？

#### 观点1: **不需要** ✅ (推荐)

**理由**:
1. **单任务足够验证核心机制**
   - 消融实验的目的是**对比有/无某创新点**
   - 不是评估在多样任务上的泛化能力
   - 一个任务足以揭示机制的作用

2. **State-event任务已经很有代表性**
   - 涉及多个文件（cross-file）
   - 涉及state machine
   - 涉及UI组件
   - 需要理解代码逻辑和事件流
   - 难度适中，不会太简单也不会太难

3. **控制变量要求一致性**
   - 同一个任务在不同配置下运行
   - 消除任务本身的干扰因素
   - 结果更容易解释

4. **时间成本考虑**
   - 9组实验 × 5次重复 × 2分钟 = 90分钟
   - 如果10个任务 × 9组 × 5次 = 900分钟（15小时）
   - 不现实

**类比**: AlphaCode、CodeGen等研究也是用HumanEval/MBPP这样的固定benchmark做消融

#### 观点2: 需要 (不推荐)

**理由**:
1. 增加结果的鲁棒性
2. 验证在不同类型任务上的泛化能力

**问题**:
1. 时间成本太高（15小时+）
2. 难以解释多任务结果（任务A有效但任务B无效怎么办？）
3. 偏离了消融实验的核心目的

---

## 推荐的消融实验方案

### 方案A: 单任务深度消融 ✅ (推荐)

**任务**: Kitchen Chaos `state-event-v1`

**实验组**: 9组（如前所述）

**重复次数**: 5次（考虑模型随机性）

**总耗时**: ~2小时

**优点**:
- 可执行性强
- 结果易于解释
- 控制变量严格
- 符合学术规范

**指标**:
- 成功率（完成SUBMIT且通过validation）
- Token使用量
- 执行轮次
- 各阶段通过率
- Mutation成功率
- Recovery成功率

---

### 方案B: 双任务验证消融 (可选，如果时间充裕)

**任务**:
1. `state-event-start-countdown` (我们用的)
2. `stove-progress-burn-warning` (不同类型：prefab + serialized reference)

**实验组**: 3组（核心消融）
- 组1: 完整系统
- 组2: 移除P1
- 组3: 移除P0+P1

**重复次数**: 3次

**总耗时**: ~1小时

**优点**:
- 验证跨任务的鲁棒性
- 两个任务覆盖不同的技术点

**缺点**:
- 增加实验复杂度
- 如果结果不一致难以解释

---

### 方案C: 单任务 + 快速抽样验证 (折中)

**主实验**: 
- 任务: `state-event-v1`
- 9组 × 5次

**验证实验**:
- 任务: `stove-progress-burn-warning`
- 3组（完整、-P1、-P0-P1）× 1次
- 只为了确认趋势一致

**总耗时**: ~2.5小时

**优点**:
- 主实验严格
- 验证实验快速确认跨任务有效性

---

## 当前测试基础设施评估

### 已有的测试支持

**1. Baseline Runner** ✅
- 完整的实验编排框架
- 支持variant切换（baseline vs innovation）
- 自动注入defect和验证oracle
- 生成标准化的报告

**2. 配置系统** ✅
- JSON-based配置
- 易于修改和复制
- 支持所有创新点的开关

**3. 日志和度量** ✅
- events.jsonl - 详细的事件日志
- trajectory.json - 完整的对话轨迹
- stage-metrics.json - 各阶段统计
- baseline-report.json - 实验报告

**4. Validation** ✅
- Unity测试自动运行
- 多模式验证（compile, editmode, playmode）
- 结构化的测试结果

---

### 缺少的内容（但不影响消融实验）

**1. 多任务支持**
- 目前只支持state-event-v1
- 但localization.json中有10个任务的gold标注
- 可以快速添加，但非必需

**2. Benchmark框架**
- benchmark.example.json提供了模板
- 但当前没有真实的benchmark配置
- 可以基于此扩展，但非必需

**3. 自动化消融脚本**
- 目前需要手动修改配置运行
- 可以写一个脚本自动生成9组配置并运行
- 会提高效率，但非必需

---

## 消融实验实施建议

### 阶段1: 准备配置 (30分钟)

**创建9个配置文件**:

```
configs/ablation/
├── group1-full.json              # 完整系统
├── group2-no-p1.json            # 移除P1
├── group3-no-evidence.json      # 移除P0+P1
├── group4-no-dynamic-tools.json # 移除动态工具暴露
├── group5-no-search-budget.json # 移除搜索预算
├── group6-no-graph.json         # 移除project graph
├── group7-no-contract.json      # 移除submission contract
├── group8-no-typed-mutations.json # 移除typed mutations
└── group9-no-validation.json    # 移除validation
```

**修改要点**:
- Group 2: `workflow.py`回退P1修改（或添加feature flag）
- Group 3: 禁用artifact持久化和evidence-based mutation
- Group 4: `exposure.py`返回所有工具
- Group 5: `SearchBudget.available()`始终true
- Group 6: 禁用context.enabled或graph_path
- Group 7: `guard_submission()`始终返回None
- Group 8: 禁用`aci.typed_mutations_enabled`
- Group 9: 跳过validation调用

---

### 阶段2: 执行实验 (2小时)

**手动执行** (简单但耗时):
```powershell
for ($i=1; $i -le 5; $i++) {
    foreach ($group in 1..9) {
        $runId = "ablation-group$group-run$i-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
        game-agent-baseline --config "configs/ablation/group$group.json" --run-id $runId
    }
}
```

**脚本自动化** (推荐):
```python
# scripts/run_ablation.py
for group in range(1, 10):
    for run in range(1, 6):
        config = f"configs/ablation/group{group}.json"
        run_id = f"ablation-group{group}-run{run}-{timestamp()}"
        subprocess.run(["game-agent-baseline", "--config", config, "--run-id", run_id])
```

---

### 阶段3: 数据收集和分析 (30分钟)

**从每次运行提取**:
```python
results = []
for run_dir in Path("artifacts/baselines/state-event-v1").iterdir():
    if not run_dir.name.startswith("ablation-"):
        continue
    
    report = json.loads((run_dir / "baseline-report.json").read_text())
    agent_result = json.loads((run_dir / "agent-result.json").read_text())
    metrics = json.loads((run_dir / "stage-metrics.json").read_text())
    
    results.append({
        "group": extract_group(run_dir.name),
        "run": extract_run(run_dir.name),
        "success": report["verified_success"],
        "total_tokens": agent_result["total_tokens"],
        "rounds": len(events),
        "mutation_success_rate": metrics.get("mutation_success_rate", 0),
        # ...
    })
```

**生成对比表**:
```python
import pandas as pd
df = pd.DataFrame(results)
summary = df.groupby("group").agg({
    "success": "mean",
    "total_tokens": "mean",
    "rounds": "mean",
}).round(2)
print(summary)
```

---

## 结论与建议

### 核心结论

**当前测试基础设施完全足够支持消融实验！**

1. ✅ 有真实的E2E测试任务（state-event-v1）
2. ✅ 有完整的实验编排框架（baseline runner）
3. ✅ 有详细的日志和度量
4. ✅ 有自动化的验证流程

**不需要额外开发测试任务！**

---

### 推荐方案

**采用方案A: 单任务深度消融**

**理由**:
1. State-event-v1任务已经足够代表性
2. 符合消融实验的学术规范
3. 时间成本合理（2小时）
4. 结果易于解释和发表

**实施步骤**:
1. 创建9个消融配置文件（30分钟）
2. 运行实验：9组 × 5次（2小时）
3. 收集和分析数据（30分钟）
4. 生成论文图表（30分钟）

**总耗时**: ~4小时

---

### 可选增强（非必需）

如果想要更强的说服力，可以考虑：

**增强1**: 添加2-3个额外任务的快速验证
- 只测试3个核心组（完整、-P1、-P0+P1）
- 每个任务1次运行
- 额外耗时：1小时

**增强2**: 编写自动化脚本
- 自动生成配置
- 自动运行实验
- 自动收集数据
- 节省手动操作时间

**增强3**: 更细粒度的消融
- P0的子组件消融（artifact vs mutation vs diagnostic）
- 但会增加实验复杂度

---

## 最终建议

**直接开始消融实验，无需额外测试开发！**

使用现有的state-event-v1任务：
- ✅ 任务质量高
- ✅ 测试基础设施完善
- ✅ 符合学术标准
- ✅ 时间成本合理

**下一步行动**:
1. 创建消融配置文件
2. 运行baseline（组1）建立参考
3. 运行核心消融组（组2、3）验证假设
4. 如果结果符合预期，完成其余组

---

**文档创建时间**: 2026-08-01  
**结论**: 测试基础设施完善，可以直接进行消融实验
