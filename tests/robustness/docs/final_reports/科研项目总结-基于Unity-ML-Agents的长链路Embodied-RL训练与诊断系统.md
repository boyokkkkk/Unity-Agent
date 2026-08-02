# 科研项目总结：基于Unity ML-Agents的长链路Embodied RL训练与诊断系统

> **项目定位**：面向保研的强化学习研究项目  
> **核心贡献**：构建可解释、可诊断的长链路任务训练与评测体系  
> **技术栈**：Unity ML-Agents, PyTorch PPO, Python评测工具链  
> **项目周期**：2026年6月 - 2026年8月（约3个月）

---

## 📋 项目概述

### 研究背景

在Embodied AI领域，长链路任务（如`approach → pickup → carry → drop`）的训练面临核心挑战：**当整体成功率看起来尚可时，研究者无法精确定位失败究竟发生在哪个前缀阶段，也难以据此制定有针对性的优化策略**。

传统方法通常只关注最终成功率这一单一指标，将复杂的多阶段失败模式压缩成一个数字，导致：
- 无法区分"接近失败"vs"拾取失败"vs"搬运失败"
- 难以判断瓶颈位于前缀还是后缀
- 优化方向依赖经验猜测而非数据驱动

### 项目目标

本项目在Unity ML-Agents框架上自建`DeliveryLab`环境，围绕条件化配送任务展开研究，目标是：

1. **构建阶段化训练体系**：将完整任务拆分为可独立验收的能力链（P1-P4b）
2. **实现Prefix-Failure诊断**：通过funnel分析精确定位长链路任务的失败环节
3. **建立Benchmark工程体系**：包含seen/unseen评测、rollout回放、诊断报告生成
4. **验证结构化先验价值**：对比显式目标指导与纯end-to-end的训练效果

---

## 🎯 核心研究问题

**在条件化长链路object-centric任务中，如何通过结构化评测体系定位失败原因，并基于诊断结果设计最小干预方案，从而比纯end-to-end PPO更有效地推进训练？**

---

## 🏗️ 系统架构

项目形成四层结构：

```
┌─────────────────────────────────────────────────────┐
│  Layer 4: Algorithm Iteration                      │
│  动态权重多目标PPO、Curriculum Learning             │
└─────────────────────────────────────────────────────┘
           ↑ 诊断结果反馈
┌─────────────────────────────────────────────────────┐
│  Layer 3: Rollout Export / Replay / Diagnostics    │
│  episode事件导出、回放、校验、failure bucket诊断    │
└─────────────────────────────────────────────────────┘
           ↑ 轨迹数据
┌─────────────────────────────────────────────────────┐
│  Layer 2: Formal Benchmark & Evaluator             │
│  阶段验证、full-task funnel、seen/unseen统计        │
└─────────────────────────────────────────────────────┘
           ↑ 训练结果
┌─────────────────────────────────────────────────────┐
│  Layer 1: Unity Training Pipeline                   │
│  P1-P4b环境语义、阶段逻辑、奖励、任务采样           │
└─────────────────────────────────────────────────────┘
```

**设计理念**：Unity负责"环境语义正确、事件可导出"，Python负责"轨迹验证、funnel汇总、诊断输出"，两侧职责明确拆分，便于后续迁移到更灵活的Python训练工作流。

---

## 🔬 核心技术方案

### 1. 阶段化训练链（P1-P4b）

将完整任务拆分为5个阶段，每个阶段独立训练并验收：

| 阶段 | 任务定义 | 成功标准 | 验证目的 |
|------|---------|---------|---------|
| **P1** | 导航接触 | 成功接触目标物体 | 验证低层接近能力 |
| **P2** | 正确拾取 | 在合法窗口内pickup | 验证pickup技能 |
| **P3** | pickup-chain迁移 | 在更复杂拓扑完成P1+P2 | 验证拓扑泛化能力 |
| **P4a** | held-start carry-drop | 已持有目标，搬运并放置 | 单独验证后缀闭环 |
| **P4b** | 完整pickup-carry-drop | 完整链路端到端 | 验证完整任务能力 |

**关键设计原则**：
- 每个阶段对应独立的observation配置，避免无关信息干扰
- P2通过bridge策略（逐步放松radius）平滑衔接P1输出分布
- P4a先验证后缀稳定性，再在P4b引入pickup前缀

### 2. Full-Task Evaluator v2

实现funnel式任务拆解，精确定位失败环节：

```python
# 8种结构化failure buckets
- timeout_before_contact         # 从未接近目标
- wrong_target_contact           # 接触了错误物体
- contact_without_pick           # 接触后未拾取
- eligible_without_pick          # 满足拾取条件但未执行
- wrong_pick                     # 拾取了错误物体
- empty_hand_zone_entry_before_pick  # 未拾取就进入目标区
- post_pick_timeout              # 拾取后超时
- wrong_place                    # 放置到错误区域
```

**评测指标体系**：
- Unconditional rate：无条件成功率
- Conditional rate：给定前置条件的成功率（如"给定正确pickup后的delivery率"）
- Latency：各阶段耗时
- Failure bucket distribution：失败类型分布

### 3. Layout Family设计

参考Overcooked-AI的布局变化思路，设计3个layout family：

| Family | 特征 | 用途 |
|--------|------|------|
| **EasyHub** | 中心辐射对称 | 基线训练 |
| **MirrorHub** | 镜像对称 | 初步泛化验证 |
| **CrossHub** | 十字交叉拓扑 | 强拓扑压力测试 |

支持**seen/unseen split**：训练时使用部分任务组合，评测时测试未见组合，验证任务级泛化能力。

### 4. Rollout Export & Diagnostics

构建完整的轨迹记录与诊断链路：

1. **Rollout Export**：训练/评测时记录episode级事件序列
   - 首次接触时间、拾取时间、放置时间
   - 错误交互事件、超时事件
   - 阶段状态转换
   
2. **Replay System**：支持轨迹回放验证

3. **Prefix Failure Diagnostics**：
   - 自动生成failure bucket统计报告
   - 识别主要瓶颈（primary bottleneck）
   - 输出针对性优化建议

### 5. 动态权重多目标PPO

基于诊断结果，设计最小结构化干预方案：

**问题识别**（来自evaluator诊断）：
- 主要残差集中在`wrong_target_contact`、`empty_hand_zone_entry_before_pick`、`contact_without_pick`
- 后缀carry/drop已基本solved（P4a验证）

**解决方案**：
- 通过`environment_parameters`动态调整奖励权重
- 三阶段curriculum：
  1. **PrefixBindFocus**：强化正确接触/拾取，加重错误惩罚
  2. **PickupConversionFocus**：保持清理但回收部分惩罚
  3. **BalancedClosure**：回归平衡权重
- 从P4a稳定checkpoint热启动

---

## 📊 实验结果

### Formal Benchmark结果（2026-06-13）

| 阶段 | 平均成功率 | 关键指标 | 结论 |
|------|-----------|---------|------|
| **P1** clean pointer | **0.9708** | timeout率0.0292 | ✅ 导航能力已稳定 |
| **P2** pointer clean | **0.9398** | wrong_pick率0.0075 | ✅ pickup能力基本成立 |
| **P2** bridge r2.3 | **0.8839** | timeout率0.1020 | ✅ bridge点可工作 |
| **P1+P2** chain r2.3 | **0.9106** | wrong_pick率0.0000 | ✅ 链路基本闭合 |
| **MirrorHub** chain | **0.8690** | wrong_pick率0.0410 | ✅ 初步泛化成立 |
| **P3 CrossHub** | **0.9022** | timeout率0.0552 | ✅ 拓扑迁移成功 |
| **P4a** held-start | **0.9844** | 后缀delivery率100% | ✅ 后缀已solved |
| **P4b** r2.5 stable | **0.9291** | pickup后delivery率100% | ⚠️ 前缀仍有残差 |

### P4b Full-Task Funnel分析

```
总成功率: 0.9322
├─ approach_contact_rate: 0.9661 ✓
│  └─ pickup_success_rate: 0.9322 ✓
│     └─ carry_drop_delivery_given_pick_rate: 1.0000 ✓✓
│        └─ drop_target_zone_given_pick_rate: 1.0000 ✓✓
```

**关键发现**：
1. ✅ 一旦正确pickup，后续carry/drop几乎100%闭环
2. ⚠️ 主要失败集中在pickup前缀：
   - `wrong_target_contact`: 接触错误物体
   - `empty_hand_zone_entry_before_pick`: 过早进入目标区
   - `contact_without_pick`: 接触后未转换为pickup

### 动态权重多目标PPO（S2）Seen/Unseen评测

| Split | Layout | 成功率 | 主要残差 |
|-------|--------|--------|---------|
| Seen | CrossHub | **0.9798** | wrong_target_contact |
| Unseen | CrossHub | **0.9647** | empty_hand_zone_entry |
| Seen | Mixed | **0.9403** | - |
| Unseen | Mixed | **1.0000** | - |

**结论**：
- 策略在CrossHub与Mixed layout下均保持高成功率
- 未见任务组合上无整体崩溃（unseen甚至优于seen）
- 残余误差进一步收敛到prefix binding问题

---

## 💡 核心创新点

### 1. 方法论层面

**从"能跑"到"能诊断"的范式转变**：
- 不再只看单一成功率，而是建立结构化failure taxonomy
- 优化方向由诊断数据驱动，而非经验猜测
- 将"盲调PPO超参"升级为"prefix-oriented最小干预"

### 2. 工程层面

**可复用的研究工程资产**：
- 阶段化训练模板（P1-P4b）
- Formal benchmark自动化生成
- Rollout export/replay/diagnostics完整链路
- Seen/unseen评测套件
- Stage gates质量门禁体系

### 3. 实验层面

**实证发现**：
- Clean-pointer在1-distractor条件下显著优于full-slot baseline
- Bridge策略（r2.3）能有效平滑阶段衔接
- 后缀carry/drop在held-start条件下可高度稳定（98.44%）
- 完整链路主瓶颈确实在pickup前缀而非后缀

---

## 🛠️ 技术实现细节

### Unity侧核心脚本

```csharp
// DeliveryLabAgent.cs - 主Agent逻辑
- 阶段化observation配置（P1-P4b）
- 动态奖励权重（environment_parameters控制）
- 事件级统计（contact/pickup/drop时间点）
- 8种failure bucket检测

// DeliveryLabAreaController.cs - 环境控制器
- Layout family切换（EasyHub/MirrorHub/CrossHub）
- Seen/unseen任务采样
- Episode初始化逻辑

// DeliveryLabRolloutExporter.cs - 轨迹导出
- Episode事件序列记录
- 稳定导出（支持Editor常驻）
- 阶段字段语义一致性保障
```

### Python侧评测工具链

```python
# deliverylab_benchmark/
├── evaluator.py              # 基础评测器
├── full_task_evaluator.py    # Full-task funnel分析
├── rollout_diagnostics.py    # Rollout诊断
├── stage_gates.py            # 阶段质量门禁
├── reporting.py              # Benchmark报告生成
└── prefix_failure_evaluator.py  # Prefix失败归因
```

### 实验管理脚本

```powershell
# ara/scripts/
- run_deliverylab_phase*.ps1           # P1-P4各阶段训练
- run_deliverylab_*_stability.ps1      # 多seed稳定性验证
- run_deliverylab_p4b_eval_inference.ps1  # 正式推理评测
```

---

## 📈 项目进展里程碑

### Week 1: 问题定位与方向转变
- ❌ 初步尝试：统一observation的end-to-end训练不稳定
- ✅ 关键转折：识别出"observation与子任务语义不对齐"是主因
- ✅ 确立方向：转向clean-pointer + 阶段化训练主线

### Week 2: 阶段化体系构建
- ✅ P1 clean-pointer稳定过线（0.9708）
- ✅ P2-bridge策略验证，确定r2.3工作点
- ✅ P1+P2 chain成功闭合（0.9106）
- ✅ MirrorHub泛化验证通过（0.8690）

### Week 3: Full-task与CrossHub推进
- ✅ P3 CrossHub拓扑迁移成功（0.9022）
- ✅ P4a held-start后缀验证（0.9844）
- ✅ P4b完整链路基本成立（0.9291）
- ✅ Full-task evaluator v2完成
- ✅ Rollout export/replay链路打通

### Week 4-5: 算法迭代与正式评测
- ✅ 动态权重多目标PPO设计与实现
- ✅ S2版本正式seen/unseen评测
- ✅ Formal benchmark自动化生成
- ✅ 完整诊断报告体系

---

## 🎓 学术价值与简历亮点

### 适合简历的描述模板

**项目1：基于Unity ML-Agents的长链路Embodied RL训练与诊断系统**

- 在Unity ML-Agents框架上自建DeliveryLab环境，研究条件化配送长链路任务（approach→pickup→carry→drop）的阶段化训练与prefix-failure诊断
- **构建阶段化训练体系**：将完整任务拆分为P1-P4b五阶段独立训练，P1导航成功率达97.08%，P4b完整链路成功率92.91%
- **实现Full-Task Evaluator v2**：设计8种结构化failure buckets，通过funnel分析精确定位失败环节，发现后缀carry/drop在held-start条件下已达98.44%，主瓶颈在pickup前缀
- **建立Benchmark工程体系**：包含seen/unseen评测、rollout导出回放、自动诊断报告生成，支持3种layout family（EasyHub/MirrorHub/CrossHub）的泛化验证
- **设计动态权重多目标PPO**：基于诊断结果针对性优化prefix问题，S2版本在CrossHub seen/unseen评测中分别达成97.98%/96.47%成功率
- **技术栈**：Unity C#、PyTorch PPO、Python评测工具链、Curriculum Learning
- **成果**：形成可复用研究工程资产，验证了结构化先验在长链路任务中优于纯end-to-end的价值

### 适合PPT的展示要点

**Slide 1: 问题背景**
- 长链路任务训练的核心挑战：失败难定位、优化无方向
- 传统方法：只看最终成功率，前缀失败被压缩

**Slide 2: 核心创新**
- 阶段化训练链（P1-P4b）
- Prefix-Failure诊断体系
- 数据驱动的最小干预

**Slide 3: 技术架构**
- 四层架构图
- Unity/Python职责分离

**Slide 4: 实验结果**
- Formal Benchmark表格
- Full-task funnel可视化
- Seen/unseen对比

**Slide 5: 关键发现**
- 后缀已solved，瓶颈在前缀
- Clean-pointer显著优于full-slot
- 动态权重有效收敛残差

**Slide 6: 工程价值**
- 可复用研究资产清单
- 向Overcooked-AI风格迁移的基础

---

## 🔗 与经典研究的联系

### Overcooked-AI范式借鉴

本项目主动参考Overcooked-AI的研究范式：
- **任务拆解**：不把任务当黑盒，按子过程建模
- **事件统计**：记录中间事件，不只看回报
- **Layout变化**：作为研究变量而非噪声
- **结构化先验**：planner/human data作为baseline

**区别**：
- Overcooked-AI聚焦多智能体协作
- DeliveryLab聚焦单智能体长链路与prefix诊断

### 与HRL/Options的关系

本项目的阶段化训练与Hierarchical RL有相似之处：
- 都强调任务分解
- 都关注子技能学习

**区别**：
- 本项目未实现自动技能发现
- 阶段划分基于任务语义而非数据驱动
- 重点在评测诊断而非层次化policy架构

---

## 🚀 后续可能方向

### 短期（2周内）
1. 继续优化prefix残差（wrong_target_contact等）
2. 探索轻量级技能抽取（从rollout轨迹提取成功片段）
3. 补充更多layout变体的泛化测试

### 中期（1-2个月）
1. 向Overcooked-AI Python侧工作流迁移
2. 补充human demonstration数据，尝试BC+RL
3. 探索KitchenChaos环境迁移（高层planner+低层skill）

### 长期研究方向
1. 自动化技能发现与组合
2. 多智能体协作扩展
3. 元学习与快速适应

---

## 📚 项目资产清单

### 代码资产
- ✅ Unity DeliveryLab完整环境（3个layout family）
- ✅ P1-P4b阶段化训练配置
- ✅ Python评测工具链（15个模块）
- ✅ 20+个实验启动脚本
- ✅ Rollout export/replay系统

### 数据资产
- ✅ Formal Benchmark (2026-06-13)
- ✅ Stage Gates质量门禁
- ✅ 60+ training runs结果
- ✅ Full-task evaluation reports
- ✅ Rollout diagnostics samples

### 文档资产
- ✅ PAPER.md（核心论文草稿）
- ✅ Week1-3问题复盘
- ✅ Overcooked-AI调研
- ✅ KitchenChaos任务定义
- ✅ 实验指令清单
- ✅ DeliveryLab设计说明书

---

## 🎯 总结陈词

本项目的真正价值，**不是单独某个成功率数字，而是将一个容易沦为"盲调PPO超参"的Unity RL项目，推进成了一套可分阶段验证、可正式benchmark、可导出轨迹、可回放诊断、可围绕failure bucket做最小干预的研究型工程系统**。

这套体系已经具备：
- 向Overcooked-AI Python侧迁移的基础
- 向自定义trainer plugin推进的接口
- 向更结构化HRL/技能方法演化的数据准备

**当前DeliveryLab已经不只是"能训练出一个模型"，而是具备了作为研究平台的完整能力**。

---

## 📞 联系方式

**项目负责人**：[你的姓名]  
**时间周期**：2026年6月 - 2026年8月  
**项目地址**：`E:\sysu-course\grad-project`  
**核心文档**：`ara/PAPER.md`

---

*本文档生成于 2026-08-02*  
*适用于保研简历、面试PPT、项目答辩等场景*
