# SkillGameAgent：面向 Unity 项目级修改的结构化理解与 Skill 迁移

## 1. 研究定位

本项目不把目标定义为“做一个功能完整的 Unity Agent”，而是研究两个更具体的问题：

1. Unity 特有的代码—资产结构是否能帮助 Agent 更准确地定位需求影响范围？
2. 基于项目结构、前置条件和验证结果的结构化 Skill，是否能提升相似但命名不同任务之间的经验迁移？

核心方法由三部分组成：

```text
Unity 类型化项目图
    → 需求影响范围定位
    → 跨文件修改计划
    → Compile / Test / Play 验证
    → Graph-Conditioned Verified Skill
```

研究贡献应表述为：

> 构建并验证一种连接 C# 符号、Scene、GameObject、Component、Prefab 和序列化引用的 Unity 类型化项目图，并研究基于该结构抽取的 Verified Skill 是否能够改善影响范围定位和跨任务迁移。

不将以下内容作为主要创新：通用 Unity Agent、普通知识图谱、长文本记忆、单纯的 Compile/Test/Play 闭环或完整支持所有 Unity 资源类型。

## 2. 研究问题与假设

### RQ1：影响范围定位

与纯代码检索和普通代码图相比，Unity 类型化代码—资产联合图能否更准确地定位需求涉及的文件、GameObject、Prefab、Scene 和依赖路径？

### RQ2：结构化 Skill 迁移

在项目图和 Agent 配置相同的情况下，Graph-Conditioned Verified Skill 是否比原始成功轨迹和文本摘要 Skill 更适合迁移到命名不同但结构相似的任务？

### RQ3：运行时验证

Play Mode 状态断言是否能发现 Compile/Test 已通过但游戏行为仍然错误的任务？它对哪些任务类型最有效？

### 假设

- **H1**：Unity 类型化项目图比纯代码检索和普通代码图具有更高的影响范围定位 Recall@K 与 Precision@K。
- **H2**：Graph-Conditioned Verified Skill 比原始轨迹和文本摘要 Skill 具有更高的跨任务迁移成功率和首轮成功率。
- **H3**：结构化 Skill 的收益在未见命名、跨文件修改和资源绑定任务上更明显，而不是只体现在同名任务上。
- **H4**：Play Mode 验证主要改善“编译通过但运行行为错误”的任务，对纯语法和纯 API 错误的收益有限。

## 3. 系统范围

### 3.1 第一版项目图

第一版只实现六类关系：


| 关系               | 含义                                   |
| ------------------ | -------------------------------------- |
| `CALLS`            | 方法调用方法                           |
| `ATTACHED_TO`      | Component 挂载于 GameObject            |
| `CONTAINS`         | Scene/Prefab 包含 GameObject           |
| `PREFAB_SOURCE`    | Prefab 实例指向源 Prefab               |
| `SERIALIZED_REF`   | SerializeField 或资源字段引用对象/资产 |
| `UNITY_EVENT_CALL` | UnityEvent 绑定并调用方法              |

节点至少包括 C# File、Class、Method、Field、MonoBehaviour、Scene、Prefab、GameObject、Component 和 Asset。

代码侧使用 Roslyn 或 Tree-sitter；Unity 侧优先使用 Unity Editor API、`AssetDatabase`、`SerializedObject`、`PrefabUtility` 和 `SceneManager` 导出结构化 JSON。可以读取 Unity YAML 辅助建立关系，但不让 LLM 直接生成或整体改写 `.unity`、`.prefab` 文件；写入通过 Editor Script 或受控工具完成。

### 3.2 存储

- SQLite：持久化节点、边、任务和实验日志；
- NetworkX：图遍历、路径查询和原型算法；
- JSON：导入导出和调试；
- 向量检索暂时使用轻量实现。只有当 Skill 数量和任务规模确实需要时再引入 FAISS。

Neo4j、Animator、Shader Graph、Addressables 和完整材质依赖不纳入第一阶段。

### 3.3 Verified Skill Schema

Skill 不保存某个具体类名或文件名，而保存可迁移的结构模式：

```yaml
skill_name: TemporaryInvincibilityAfterDamage
intent: add temporary invincibility after receiving damage
preconditions:
  required_node_types: [DamageReceiver, HealthState, VisualRenderer]
  graph_pattern:
    - damage entry calls damage application
    - health state is attached to target object
transformation:
  - insert invincibility state
  - guard damage entry
  - schedule state reset
postconditions:
  - repeated damage within interval is ignored
validators:
  - compile
  - playmode_state_assertion
  - log_assertion
failure_patterns:
  - state stored in attacker instead of target
  - renderer reference missing
```

只有在 Compile、Test 或 Play 验证通过后，轨迹才可以进入 Verified Skill 库。失败轨迹保留为 failure pattern，不作为成功模板直接复用。

## 4. 受控实验设计

### 4.1 控制变量

所有配置使用相同的：

- 模型与系统提示词；
- Agent 工具集合和工具调用流程；
- 最大轮数与 Token 预算；
- 编译、测试、运行脚本；
- Unity 版本和项目初始状态。

实验中只改变项目上下文、Skill 形式或运行时反馈，避免把 Agent 框架、工具数量和上下文长度同时改变。

### 4.2 实验一：项目图对影响范围定位的作用


| 配置 | 项目上下文             | Skill | 反馈         |
| ---- | ---------------------- | ----- | ------------ |
| A0   | 文本 Code-RAG          | 无    | Compile/Test |
| A1   | 普通代码图             | 无    | Compile/Test |
| A2   | Unity 代码—资产联合图 | 无    | Compile/Test |

输入需求后，先要求 Agent 输出影响范围，不立即执行修改。使用人工标注的 gold 文件、对象和依赖路径计算定位指标。

### 4.3 实验二：Skill 形式对迁移的作用

固定使用 A2 的项目图，仅改变 Skill：


| 配置 | Skill                            |
| ---- | -------------------------------- |
| A2-T | 原始成功轨迹                     |
| A2-S | 文本摘要 Skill                   |
| A2-G | Graph-Conditioned Verified Skill |

任务分为：

- **源任务**：用于产生 Skill；
- **同族迁移任务**：结构相似但类名、方法名和资源名不同；
- **非适用任务**：表面词汇相似但图结构不满足前置条件。

重点比较 A2-G 是否提高同族迁移，同时降低非适用任务中的负迁移。

### 4.4 实验三：运行时验证的作用

只在 A2-G 上增加一个变量：


| 配置     | 验证闭环                       |
| -------- | ------------------------------ |
| A2-G-CT  | Compile + Test                 |
| A2-G-CTP | Compile + Test + Play 状态断言 |

Play Mode 不是所有任务的必需步骤。对于 UI、粒子和闪烁等无法完全由状态表示的任务，可补充截图；其他任务优先使用 GameObject 存在性、Component 字段、玩家位置、生命值、状态机状态和日志断言。

## 5. 任务集

第一阶段使用 8–12 个自建 Unity 2D 任务，分为三个 Skill 家族：

### 家族 A：角色与敌人行为

- 玩家冲刺；
- 敌人突进；
- NPC 短距离闪避。

### 家族 B：临时状态

- 受击无敌；
- 拾取护盾；
- 技能释放后的霸体。

### 家族 C：交互与状态绑定

- 拾取道具；
- 开门；
- 进入区域触发任务。

每个家族至少包含一个源任务、两个迁移任务和一个负迁移控制任务。必须改变类名、方法名、层级或资源命名，避免简单文本匹配即可解决。

SWE-game-bench 只选取 4–8 个可复现的 Golden Unity Issue，作为外部验证集，而不是承担完整 Skill 迁移实验。若环境部署不稳定，优先完成自建任务上的受控消融，再将真实 Issue 作为扩展实验。

## 6. 评价指标

### 6.1 主要指标

- File Recall@K / Precision@K；
- GameObject Recall@K；
- Prefab/Scene Recall@K；
- Dependency Path Recall；
- Compile Pass Rate；
- Test Pass Rate；
- Play Behavior Pass Rate；
- End-to-End Task Success；
- Skill Transfer Success Rate；
- Negative Transfer Rate；
- First-pass Success Rate。

### 6.2 次要指标

- Token 使用量；
- 工具调用轮数；
- 平均修复轮数；
- 执行时间和 API 成本。

任务数量较少时，报告每个任务的结果、二元成功率的 bootstrap 置信区间，并使用配对 McNemar 检验比较成功率；Token、轮数等配对成本指标可使用 Wilcoxon 检验。不能只报告平均值。

## 7. 消融实验

至少完成以下四组：

1. 去掉 Unity 项目图：验证图是否真正带来收益；
2. 去掉 Skill：验证迁移收益是否来自经验复用；
3. 使用文本 Skill 替代图条件 Skill：验证结构化表示是否有额外贡献；
4. 去掉 Play Mode：验证运行反馈对行为正确性的独立贡献。

不要同时改变图、Skill、模型、工具和 Token 预算，否则无法解释结果。

## 8. 六周执行计划

### 第 1 周：统一 Agent 基线

- 跑通一个小型 Unity 2D 项目；
- 实现文件读取、代码修改、Compile 和 Test；
- 完成 3 个任务；
- 固定日志格式和实验配置。

### 第 2 周：Unity 项目图

- 完成 Roslyn/Tree-sitter 代码解析；
- 通过 Editor API 导出 Scene、Prefab、GameObject 和 Component；
- 实现六类边；
- 完成 A0/A1/A2 的定位评测。

### 第 3 周：结构化 Skill

- 固定 Skill Schema；
- 从成功轨迹中抽取前置条件、变换、后置条件和失败模式；
- 完成文本 Skill 与 Graph Skill 的检索和匹配。

### 第 4 周：迁移任务

- 完成三个 Skill 家族；
- 构造命名不同的迁移任务和负迁移任务；
- 完成 A2-T、A2-S、A2-G 对比。

### 第 5 周：运行时验证与外部任务

- 加入 Play Mode 状态断言；
- 完成 A2-G-CT 与 A2-G-CTP 对比；
- 运行 4–8 个 SWE-game-bench Golden 任务。

### 第 6 周：统计与分析

- 完成消融、失败案例和负迁移分析；
- 汇总定位、迁移、行为正确性和成本指标；
- 形成系统图、实验表、结果图和技术报告。

### 止损条件

第 3 周结束时，如果项目图无法稳定导出或定位评测无法完成，则暂停大规模 Skill 迁移和截图评测，先完成“项目图 → 影响范围定位”的最小闭环。Play Mode 和 SWE-game-bench 都属于可延期扩展项。

## 9. 最终贡献表述

本文研究 Unity 仓库级功能修改中的结构化项目理解与经验迁移问题。首先，构建连接 C# 程序符号、Scene、GameObject、Component、Prefab 和序列化引用的 Unity 类型化代码—资产依赖图，并将其用于需求影响范围定位。其次，将成功开发轨迹抽象为包含图前置条件、变换步骤、后置条件、验证器和失败模式的 Graph-Conditioned Verified Skill，评估其在命名不同但结构相似任务上的迁移能力。最后，通过 Compile、Test 和 Play Mode 状态断言建立受控验证闭环，分析项目图、结构化 Skill 和运行反馈对定位准确率、任务成功率、负迁移率和上下文成本的独立影响。

## 10. 优先级总结

### 必须完成

- 六类 Unity 项目图关系；
- A0/A1/A2 定位对照；
- 文本 Skill 与 Graph Skill 对照；
- 负迁移任务；
- Recall@K、迁移成功率和 Compile/Test 成功率；
- 至少一组 Play Mode 消融。

### 有余力再完成

- SWE-game-bench 外部验证；
- 截图和视觉反馈；
- FAISS；
- 更多资源类型和更多任务。

### 暂不做

- 完整 Unity 资源生态建模；
- Neo4j 等复杂基础设施；
- 多种大型 Agent 框架并行比较；
- 20 个以上任务的大规模实验；
- 将通用 Unity Agent 作为论文主贡献。
