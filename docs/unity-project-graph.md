# Unity 类型化项目图实现

## 1. 实现范围

当前实现对应科研方案的第一项创新：连接 C# 符号与 Unity 资产结构的类型化项目图，并以同一任务集完成 A0/A1/A2 定位消融。

代码解析使用本机 .NET SDK 中的 Roslyn 4.14，不依赖正则表达式模拟 C# AST。Unity 结构通过隔离工程中的 Editor API 导出，不直接读取或修改源工程的 Scene、Prefab YAML。

图使用稳定 JSON Schema，并同时写入 SQLite 和 NetworkX：

- JSON 用于实验归档与调试；
- SQLite 用于持久化、按类型查询和邻接查询；
- NetworkX 用于路径搜索和 A1/A2 图传播。

## 2. 节点和六类边

节点类型：

- `CSHARP_FILE`
- `CLASS`
- `METHOD`
- `FIELD`
- `MONO_BEHAVIOUR`
- `SCENE`
- `PREFAB`
- `GAME_OBJECT`
- `COMPONENT`
- `ASSET`

边类型：

| 边 | 来源 | 目标 | 提取方式 |
| --- | --- | --- | --- |
| `CALLS` | Method | Method | Roslyn `InvocationExpressionSyntax` |
| `ATTACHED_TO` | Component | GameObject | `GameObject.GetComponents` |
| `CONTAINS` | Scene/Prefab/GameObject | GameObject | Scene 根节点和 Transform 层级 |
| `PREFAB_SOURCE` | GameObject | Prefab | `PrefabUtility.GetPrefabAssetPathOfNearestInstanceRoot` |
| `SERIALIZED_REF` | Field/Component | Object/Asset | `SerializedObject` 的 ObjectReference |
| `UNITY_EVENT_CALL` | Field/Component | Method | Editor 持久 UnityEvent 和 Roslyn `AddListener` |

项目中按钮监听全部通过 `onClick.AddListener` 动态注册，YAML 中不存在非空 `m_MethodName`。因此 `UNITY_EVENT_CALL` 同时支持：

1. Editor API 可见的持久监听；
2. Roslyn 可见的动态 `AddListener(lambda/method group)`。

代码类型到 Component 实例的对应关系保存在 Component 的 `code_symbol_id` 属性中。它在检索期形成内部桥接关系，不作为第七类持久化边，避免破坏六类边消融定义。

## 3. 构建流程

```text
Unity source project (read-only)
    ├── Roslyn AST export
    │     └── C# files/classes/methods/fields/CALLS/dynamic UnityEvent
    └── filtered isolated copy
          └── Unity Editor API export
                └── Scene/Prefab/GameObject/Component/references

merge + symbol resolution
    ├── project-graph.json
    ├── project-graph.sqlite3
    └── build-report.json
```

构建命令：

```powershell
game-agent-graph build `
  --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
  --editor "D:\Unity\unity editor\2021.3.45f1c1\Editor\Unity.exe" `
  --output "artifacts\project-graph\kitchen-chaos-full"
```

只构建普通代码图：

```powershell
game-agent-graph build `
  --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
  --output "artifacts\project-graph\kitchen-chaos-code-only" `
  --code-only
```

Unity 是 GUI 子系统程序。在受限执行环境中，它可能在 Licensing 初始化前静默等待；实验执行器必须在允许 Unity 与 Licensing Client 通信的宿主环境运行。有效启动的判断不是进程存在，而是专用日志和隔离工程 `Library` 已创建。

## 4. A0/A1/A2 定位消融

三个变体共享相同查询、候选工程、gold 和 K：

- A0：BM25 风格文本 Code-RAG，仅返回 C# 文件；
- A1：A0 与普通代码 `CALLS` 图传播融合；
- A2：A0 与完整 Unity 代码—资产图传播融合。

A2 可以额外返回 GameObject、Scene/Prefab/Asset 和依赖路径。图传播使用固定权重和固定融合系数，不调用 LLM，避免模型随机性污染结构消融。

评测命令：

```powershell
game-agent-graph evaluate `
  --graph "artifacts\project-graph\kitchen-chaos-full\project-graph.json" `
  --tasks "configs\localization.kitchen-chaos.json" `
  --output "artifacts\project-graph\kitchen-chaos-full\localization-evaluation.json"
```

当前 Kitchen Chaos 定位集包含十个手工 gold 任务：

1. 游戏开始状态事件、教程 UI 和倒计时 UI；
2. 炉灶状态、进度条和烧焦警告；
3. 配方交付、结果弹窗和 Delivery UI。
4. 玩家移动、输入、动画和音效；
5. 切菜柜台、动画和进度条；
6. 盘子生成、移除和堆叠视觉；
7. 盘子配料、完整视觉和图标；
8. 容器柜台、食材生成和开合动画；
9. 暂停菜单、选项界面和按键重绑定；
10. 音乐、音效音量和音频资源。

每个任务独立标注文件、GameObject、Scene/Prefab/Asset 和依赖路径。评测输出保留全部 30 条任务—变体结果，不只保存聚合均值。

### 4.1 统计推断

对每个 A0/A1/A2 指标计算：

- 10,000 次任务级 percentile bootstrap 95% 置信区间；
- A2-vs-A0 和 A2-vs-A1 的任务级双侧精确符号置换检验；
- 将“该任务 gold 全部召回”二值化后的精确 McNemar 检验；
- 每个比较和检验族内的 Holm 多重比较校正；
- 胜/平/负任务数和平均配对差值。

任务是统计抽样单位，不能把节点或文件当作独立样本。

## 5. 真实结果

真实图规模：

- 3513 个节点；
- 8479 条边；
- 55 个 C# 文件、3 个 Scene、65 个 Prefab；
- 737 个 GameObject、2008 个 Component。

六类边计数：

| Edge | Count |
| --- | ---: |
| `CALLS` | 589 |
| `ATTACHED_TO` | 2008 |
| `CONTAINS` | 737 |
| `PREFAB_SOURCE` | 525 |
| `SERIALIZED_REF` | 4561 |
| `UNITY_EVENT_CALL` | 59 |

十任务结果：

| Metric | A0 | A1 | A2 |
| --- | ---: | ---: | ---: |
| File Recall@5 | 0.762 | 0.787 | **0.812** |
| File Precision@5 | 0.660 | 0.680 | **0.700** |
| File Recall@10 | 0.827 | 0.857 | **0.910** |
| GameObject Recall@10 | 0 | 0 | **0.858** |
| Asset Recall@5 | 0 | 0 | **0.300** |
| Dependency Path Recall | 0 | 0 | **0.800** |

A2 的 File Recall@5 相对 A0 平均增加 0.05，但只有 2 胜、8 平，精确配对 `p=0.5`，不能宣称显著。GameObject Recall@10 在 10 个任务中全部胜出，精确配对 `p=0.001953`，Holm 校正后 `p=0.033203`。Dependency Path Recall 原始配对 `p=0.0078125`，但全指标 Holm 校正后 `p=0.109375`，当前样本下仍不能宣称显著。

## 6. Agent 如何使用项目图

Agent 通过只读 CLI 查询项目图：

```powershell
game-agent-graph query `
  --graph "artifacts\project-graph\kitchen-chaos-full\project-graph.json" `
  --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
  --variant A2 `
  --limit 10 `
  --query "需求自然语言" `
  --output "graph-query.json"
```

推荐工作流：

1. 在第一次全仓库搜索前执行图查询；
2. 从 `files` 选择少量 C# 候选做源码核验；
3. 用 `game_objects` 和 `assets` 确认 Scene/Prefab 绑定位置；
4. 用 `dependency_paths` 解释跨代码—资产影响链；
5. 最终影响范围中区分“图推荐”和“源码确认”；
6. 定位任务禁止修改源码。

`audit-agent` 会在隔离副本中执行真实 Agent，并检查：

- 是否实际调用 `game-agent-graph query`；
- 图查询是否发生在手工搜索和文件读取之前；
- 查询是否成功；
- Agent 后续读取了多少图推荐文件；
- 最终文件、GameObject 和 Asset 的 gold Recall/Precision；
- 是否引用具体图节点或边作为证据；
- 是否保持零源码修改。

只有“查询成功、先图后读、File Recall 不低于 0.5、零源码修改”同时成立，才标记 `correctly_applied=true`。

```powershell
game-agent-graph audit-agent `
  --project "E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos" `
  --graph "artifacts\project-graph\kitchen-chaos-full\project-graph.json" `
  --tasks "configs\localization.kitchen-chaos.json" `
  --task-id "state-event-start-countdown" `
  --config "configs\kitchen_chaos.json"
```

该命令会调用配置中的外部模型 API。运行前必须明确确认任务描述和 Agent 按需读取的源码片段允许发送到该 API。
