# Unity 状态事件缺陷 Baseline 与阶段观测设计

## 1. 目标

在不污染原始 Kitchen Chaos 工程、不启用项目专用 Skill、也不改变 Agent 决策行为的条件下，完成一次可复现的 Unity 状态机缺陷修复实验。

实验需要回答三个问题：

1. 当前 Agent 能否根据玩家可见症状定位状态切换与 UI 刷新链路中的根因，并完成最小修复。
2. Agent 的时间、Token、工具调用和上下文主要消耗在哪些阶段。
3. baseline 暴露出的最大量化缺口是什么，从而为 Unity 项目图、上下文压缩、验证闭环或影响范围分析等创新点提供证据。

本设计只定义 baseline 基础设施和实验协议。创新点在 baseline 报告生成后根据最大缺口选择，不预先将某个方案设定为必然结论。

## 2. 固定实验条件

### 2.1 真实任务

Agent 收到以下自然语言任务：

> 玩家在开始界面按下交互键后，游戏应进入倒计时；目前教程界面没有关闭，倒计时界面也没有出现。问题可能位于游戏状态切换与 UI 刷新链路。请定位根因，进行最小修复，并通过相关 Unity 测试验证。

任务描述同时包含玩家可见症状和组件级线索，但不暴露事件名称、根因文件或标准补丁。

### 2.2 可控缺陷

在隔离工作区中删除 `KitchenGameManager` 从 `WaitingToStart` 进入 `CountdownToStart` 时的 `OnStateChanged` 通知。

预期影响是：

- 游戏状态已经进入倒计时；
- 订阅状态事件的 `TutorialUI` 不会及时隐藏；
- `GameStartCountdownUI` 不会及时显示；
- 编译可以通过，因此必须依赖行为测试发现缺陷。

正确修复必须恢复该状态转换的事件传播，且不得通过直接隐藏 UI、跳过倒计时、修改测试或引入额外状态转换绕过问题。

### 2.3 Agent 与资源参数

baseline 固定使用：

- 模型：`openai/qwen-plus`
- 温度：`0.0`
- 随机种子：`42`
- 项目专用 Skill：全部禁用
- 单轮最大输入：`12000` Token
- 单次最大输出：`2048` Token
- 最大总量：`81920` Token
- 最大 Agent 轮数：`40`
- 单个工具观测上限：`12000` 字符

baseline 对上下文只观测、不干预。不得增加自动摘要、项目图检索、额外输出裁剪或人工纠偏。

## 3. 实验隔离与数据流

完整流程为：

```text
原始 Kitchen Chaos 工程
  -> 创建隔离工作区
  -> 注入唯一状态事件缺陷
  -> 记录基线哈希、缺陷补丁和实验配置
  -> 以 no-skill 条件启动单轮 Agent 任务
  -> 实时写入增强事件和自然语言对话投影
  -> Agent 提交、失败或触及资源限制
  -> 运行公共 Compile/EditMode/PlayMode
  -> 临时注入隐藏事件回归测试
  -> 运行隐藏 EditMode/PlayMode
  -> 保存验证证据并移除隐藏测试
  -> 离线重建阶段和指标
  -> 生成 baseline 缺陷报告
  -> 校验原始工程未发生变化
```

Agent 可以在隔离工作区中修改源码和添加自己的测试。原始 Unity 工程只作为工作区来源，不接收实验写入。

建议产物结构：

```text
artifacts/baselines/state-event-v1/<run_id>/
  config.json
  defect-manifest.json
  workspace-baseline.json
  events.jsonl
  conversation.jsonl
  trajectory.json
  diff.patch
  validation/public/
    summary.json
    compile.log
    editmode.log
    editmode-results.xml
    playmode.log
    playmode-results.xml
  validation/hidden/
    summary.json
    editmode.log
    editmode-results.xml
    playmode.log
    playmode-results.xml
  stage-metrics.json
  baseline-report.json
  baseline-report.md
```

`events.jsonl` 是阶段分析的事实来源。`stage-metrics.json` 和报告均为可重复计算的派生产物。

## 4. 组件边界

### 4.1 BaselineCase

`BaselineCase` 负责声明和准备实验，不负责运行 Agent 或计算指标。

输入包括：

- 任务文本；
- 源工程和隔离模式；
- 缺陷补丁；
- oracle 相关文件集合；
- 模型、预算和 Skill 开关；
- 公共与隐藏验证配置。

它必须在 Agent 启动前验证：

- 原始工程有效；
- 隔离工作区创建成功；
- 缺陷补丁只命中预期位置；
- 注入后的缺陷片段与 manifest 一致；
- 项目专用 Skill 确实处于禁用状态。

### 4.2 TelemetryEnricher

`TelemetryEnricher` 复用现有事件管道，仅补充行为中立的观测字段：

- 单调时钟和事件持续时间；
- 模型请求输入、输出和累计 Token；
- 工具命令类别；
- 工具返回码和持续时间；
- 工具原始输出与保留输出的字符数、行数和摘要哈希；
- 读取、搜索、写入和验证涉及的文件路径；
- 每次写入后的 diff 哈希、修改文件和行数；
- 重复命令、重复观测和无进展计数。

它不得改变提示词、消息历史、工具返回内容、工具执行顺序或 Agent 限制策略。

### 4.3 ConversationProjector

`ConversationProjector` 将事实事件投影为用户可见的 `conversation.jsonl`，但不额外调用模型。

记录类型为：

- `user`：初始自然语言任务；
- `assistant_progress`：由确定性事件模板生成的阶段进度；
- `assistant_final`：Agent 的最终提交；
- `system_failure`：Agent 未提交时的可读停止原因和已完成进度。

baseline 是单轮受控实验。执行过程中不接受用户追加提示或纠偏，以免引入不可复现变量。

### 4.4 StageAnalyzer

`StageAnalyzer` 在任务结束后读取原始事件、trajectory 和 diff 快照，输出阶段划分、里程碑和指标。它不参与在线 Agent 决策。

关键时间点为：

- `T0`：用户任务提交；
- `T1`：首次工具调用；
- `T2`：首次命中相关文件；
- `T3`：首次命中根因文件；
- `T4`：首次源码修改；
- `T5`：首次形成语义正确的候选补丁；
- `T6`：首次执行验证；
- `T7`：Agent 提交或停止；
- `T8`：公共验证结束；
- `T9`：隐藏验证结束。

阶段规则和 oracle 里程碑必须同时保存。阶段规则可以迭代，但不得覆盖原始事件。

### 4.5 OracleValidator

`OracleValidator` 负责公共验证和提交后隐藏验证。

公共验证使用 Agent 执行结束时工作区内已有的测试，依次运行：

1. Compile；
2. EditMode；
3. PlayMode。

隐藏验证随后临时创建 `Assets/Tests/BaselineOracle`，验证：

- 交互触发后状态进入 `CountdownToStart`；
- `OnStateChanged` 产生一次预期通知；
- Tutorial 和 Countdown UI 所依赖的公开状态查询结果正确；
- 修复没有直接进入 `GamePlaying`；
- 修复没有产生额外状态转换。

隐藏测试只在 Agent 停止后注入，Agent 不能读取或修改它。隐藏验证结束后删除临时测试目录，并保留注入文件的哈希和验证 XML 作为证据。

Unity 2021.3 的 EditMode 和 PlayMode 命令不得组合使用 `-quit` 和 `Start-Process -Wait`。验证器应启动独立进程、记录精确 PID、轮询结果 XML，并在结果可解析后进行有界进程收尾。Compile 可以使用正常的 batchmode 退出流程。

### 4.6 BaselineReportBuilder

`BaselineReportBuilder` 汇总结果，不重新解释或修改原始事件。它输出机器可读 JSON 和用户可读 Markdown，内容包括：

- 实验是否有效；
- Agent 是否提交；
- 公共和隐藏验证结果；
- 阶段耗时与资源消耗；
- 上下文、导航、修改和验证缺口；
- 自然语言声明与证据的一致性；
- 最大缺口及其支持的创新方向。

## 5. 指标定义

### 5.1 任务正确性

- `agent_submitted`：Agent 是否主动提交。
- `compile_passed`：公共编译是否通过。
- `public_editmode_passed`：公共 EditMode 是否通过且测试数大于零。
- `public_playmode_passed`：公共 PlayMode 是否通过且测试数大于零。
- `hidden_editmode_passed`：隐藏 EditMode 是否通过。
- `hidden_playmode_passed`：隐藏 PlayMode 是否通过。
- `verified_success`：Agent 已提交且所有要求的公共与隐藏验证均通过。

实验有效性与 Agent 成功分开。Agent 超限、未提交或修复失败仍可形成有效 baseline，只要实验基础设施和证据完整。

### 5.2 源码导航

- 首次相关文件命中时间；
- 根因文件在首次访问文件序列中的排名；
- 相关文件召回率；
- 相关文件读取字符数占比；
- 无关源码读取比例；
- 搜索后无文件命中的次数；
- 同一文件重复读取比例；
- 修改前累计读取文件数和字符数。

oracle 相关文件至少包括：

- `KitchenGameManager.cs`
- `TutorialUI.cs`
- `GameStartCountdownUI.cs`

### 5.3 上下文

- 每轮 prompt、completion 和累计 Token；
- 每轮上下文占用率；
- 工具原始与保留输出字符数；
- 被观测上限截断的工具调用数；
- 重复观测 Token 估算；
- 上下文浪费率；
- 正确补丁出现前消耗的 Token；
- 提交或停止时剩余 Token。

上下文浪费率定义为：

```text
重复观测 Token 估算 / 总输入 Token
```

重复观测通过规范化文本块哈希和相似片段匹配计算，报告中同时保存精确重复与近似重复两个值。

### 5.4 行为与修改

- 模型和工具调用总数；
- 工具成功率；
- 重复命令数；
- 无进展轮次；
- 首次写入时间；
- 修改文件数；
- 新增和删除行数；
- 修复范围外修改行数；
- 返工次数；
- 正确候选补丁首次出现时间。

范围污染率定义为：

```text
与 oracle 修复无关的修改行 / 全部修改行
```

如果没有修改，范围污染率记为 `0`，同时由 `verified_success=false` 表明任务未完成，避免除零和误读。

### 5.5 验证与声明

- 首次验证时间；
- 公共和隐藏验证持续时间；
- 验证尝试次数；
- XML 缺失、超时、工程锁、编译错误和测试断言失败的独立计数；
- 正确补丁出现到首次验证的延迟；
- 最终回答中根因、改动和验证声明的证据支持比例。

声明可信度定义为：

```text
被日志、diff 或 XML 支持的可验证声明 / 最终回答中的可验证声明
```

Agent 没有最终回答时，该指标记为 `null`，并单独记录 `missing_final_answer=true`。

### 5.6 自然语言体验

- 首次进度反馈延迟；
- 阶段进度消息数量；
- 重复进度消息数量；
- 是否生成最终回答；
- 失败时是否生成可读停止说明；
- 最终回答是否覆盖根因、改动、验证和限制四类信息。

## 6. 阶段重建规则

阶段重建采用确定性事件和文件里程碑：

1. `task_understanding`：从 `T0` 到 `T1`。
2. `source_localization`：从 `T1` 到首次根因文件命中；若未命中则延续到 `T7`。
3. `diagnosis`：从首次根因文件命中到首次源码修改；若未修改则延续到 `T7`。
4. `editing`：从首次源码修改到首次验证；若未验证则延续到 `T7`。
5. `self_validation`：从首次验证到 `T7`。
6. `public_validation`：从 `T7` 到 `T8`。
7. `hidden_validation`：从 `T8` 到 `T9`。

若 Agent 在同一阶段多次回退，例如验证失败后再次编辑，主阶段按首次边界保持稳定，同时用 `phase_reentry` 记录回退次数和耗时，避免丢失返工信息。

`T5` 不用于在线阶段切换。它由任务结束后的 diff 序列和隐藏 oracle 重放确定，因此不会向 Agent 泄露标准答案。

## 7. 缺点量化与创新决策

baseline 报告按以下证据选择优先创新方向：

- 导航精度低、根因排名靠后、无关读取比例高：优先 Unity 项目图和依赖检索。
- 重复观测和上下文浪费率高：优先图约束上下文压缩或证据记忆。
- 正确补丁较早出现但验证延迟高：优先自动验证策略和闭环调度。
- 范围污染率高或出现跨层绕过修复：优先影响范围分析和约束编辑。
- 声明可信度低：优先 evidence-backed submission。

一次 baseline 用于诊断和决定首个创新原型，不用于形成具有统计显著性的论文结论。创新实现后应使用相同任务、模型、预算、验证器和阶段分析规则进行配对复测；正式结论需要增加任务数和随机种子。

## 8. 异常与有效性判定

以下情况属于 Agent 失败，但实验仍可有效：

- Token、轮数、时间或成本超限；
- Agent 未提交；
- 修改错误文件；
- 公共或隐藏测试失败；
- 最终回答缺失。

以下情况属于实验基础设施失败，本次结果不得用于比较：

- 缺陷没有准确注入；
- no-skill 配置未生效；
- 原始工程被修改；
- 隐藏测试在 Agent 运行期间可见；
- 隐藏测试无法清理；
- Unity 验证器没有保存足够证据区分超时、XML 缺失和测试失败；
- telemetry 缺少重建关键阶段所需的事件。

所有失败都必须生成 `baseline-report.json`。基础设施失败报告应明确标记 `experiment_valid=false`，不得归因于 Agent。

## 9. 测试策略

### 9.1 单元测试

覆盖：

- 缺陷 manifest 校验；
- telemetry 字段和单调时间；
- 命令类别和文件路径提取；
- 重复观测识别；
- 阶段边界及阶段回退；
- 指标公式的零值和缺失值；
- 对话投影；
- Agent 失败与基础设施失败的分离。

### 9.2 合成轨迹测试

至少构造：

- 最小修复并一次验证通过；
- 大量无关搜索后修复；
- 正确补丁出现但未验证；
- 修改 UI 绕过根因；
- Token 超限且没有提交；
- Unity XML 缺失；
- 验证失败后返工并成功。

### 9.3 Unity 验证器测试

覆盖：

- Compile 成功与编译错误；
- EditMode 和 PlayMode 生成非空 XML；
- XML 中零测试不计为通过；
- 断言失败；
- Unity 进程延迟退出；
- 结果已落盘但进程未退出；
- 超时、工程锁和许可错误的独立归因；
- 只终止本次启动的精确 PID。

### 9.4 真实端到端 baseline

验收条件为：

- 原始工程没有变化；
- 隔离工作区只包含预期缺陷和 Agent 修改；
- Skill 禁用证据存在；
- Agent 完成一次无人为干预执行；
- 公共和隐藏验证均产生结构化结果；
- `events.jsonl`、`conversation.jsonl`、`stage-metrics.json` 和两类报告齐全；
- 报告可以指出至少一个由数据支持的主要缺口；
- 无论 Agent 成功或失败，都能给出明确、可复查的失败归因。

## 10. 非目标

本轮不实现：

- Unity 项目图本身；
- 自动上下文摘要；
- Verified Skill；
- 多轮人工纠偏；
- 多模型、多任务或多种子统计实验；
- 前端复杂指标可视化。

本轮只建立可信 baseline、阶段观测、隐藏验证和缺点量化闭环。完成真实 baseline 后，再根据报告选择并设计第一个创新点。
