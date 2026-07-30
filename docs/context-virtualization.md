# Unity 项目上下文虚拟化（P1）

## 目标

P1 将 Unity 项目图从一次性 observation 提升为版本化的项目级语义内存。完整图、完整消息轨迹和原始工具输出保留在模型上下文之外；每个任务只把当前工作集、结构化证据和最近失败映射进本轮模型输入。

    ProjectGraph + source files
            |
            v
    ProjectContextStore  ---- graph version / dirty nodes / invalidations
            |
            v
    TaskWorkingSet       ---- task-local node references and paged details
            |
            +---- EvidenceLedger
            +---- ContextMemory
            |
            v
    ContextAssembler     ---- two-message model view

完整的 agent.messages 仍写入 trajectory 供审计，但 DefaultAgent.query() 使用 ContextAssembler 生成的视图调用模型。

## 核心对象

ProjectContextStore 加载并缓存不可变 ProjectGraph，维护 GraphVersion、path/node/signature 索引、多个任务的 TaskWorkingSet、dirty node、失效历史和 context hit/miss 指标。工程 revision 优先使用图 metadata 中的 project_revision、git_commit 或 tree_hash，否则使用图文件摘要。

TaskWorkingSet 保存稳定节点引用、相关度、状态、访问次数、证据 ID 和可换出的 detail。第一次 materialize 是 miss；同一未失效 detail 的后续访问是 hit。压缩可清除 detail，但不会删除节点引用或 EvidenceLedger。

EvidenceLedger 的状态包括：

- suggested：项目图推荐，不能作为已确认事实；
- observed：Agent 已读取相关源码或资产；
- source_verified：源码或资产证据已核验；
- runtime_verified：编译或测试证据已核验；
- rejected：假设或候选已证伪。

ContextMemory 持久保存 decisions、verified_facts、rejected_hypotheses、unresolved_questions、changed_files、pending_validations、last_failure、artifact_references 和 conversation_summary，不依赖自然语言摘要保存关键状态。

## 每轮模型视图

ContextAssembler 每轮只发送原始稳定 system message，以及一个 virtual-project-context user message。后者包含：

- 原始任务、最新 turn 请求、当前 phase 和 phase goal；
- 结构化 plan、ContextMemory 和证据账本；
- 工作集节点引用与少量按需 materialize 的节点详情；
- 最近工具结果的结构化摘要；
- token、时间和调用预算；
- context metrics。

原始工具输出由 LocalEnvironment 写入 tool-outputs。模型视图只保留 summary、artifact_ref、important_ranges 和 truncated；需要原文时再按 artifact_ref 重新加载。

## 压缩和失效规则

压缩在完整历史达到 token 阈值、phase 变化、旧工具结果超过保留数量或工程变化时触发：

1. 原始工具输出 artifact 化；
2. 只保留最近 N 个结构化工具摘要；
3. 换出非活跃节点 detail；
4. 永久保留 EvidenceLedger、ContextMemory 和 artifact references；
5. 生成确定性短说明，不调用额外摘要模型。

失效与 remap 规则：

- 初始化记录图引用文件的 mtime 和 size；
- 每轮 assemble 前检测变化，PowerShell 写操作也立即触发失效；
- 修改路径直接命中的节点和一跳相邻节点标记 dirty；
- dirty detail 不作为 cache hit 返回；
- 加载新图后先按 node ID remap，再按 kind/path/name signature remap；
- 无法 remap 的节点保持 stale。

## 指标

    context_hit_rate = hits / (hits + misses)
    context_miss_rate = misses / (hits + misses)
    working_set_precision = relevant_labeled_nodes / active_working_set_nodes
    working_set_judged_precision = relevant_labeled_nodes / judged_nodes
    working_set_judgment_coverage = judged_nodes / active_working_set_nodes
    tokens_avoided_estimate += max(0, raw_history_tokens - assembled_view_tokens)

working_set_precision 在没有 relevance label 时为 0，并通过 judgment coverage 表明标注覆盖率，避免把未核验推荐误报为高 precision。指标写入 trajectory 的 context.metrics；项目状态写入 project-context-state.json。

## 配置

configs/kitchen_chaos.json 顶层 context 提供 enabled、graph_path、state_path、auto_locate、工作集/详情/工具结果上限和 compression_trigger_ratio。相对 graph_path 以仓库根目录解析；空路径表示启用上下文虚拟化但不加载项目图，便于 P1 消融。

## P1 边界

PowerShell 操作仍只能用确定性命令分类和路径提取更新 phase、changed files、最近失败与待验证项。P2 第一层已经增加只读结构化查询：搜索/列表/引用结果写入 observed evidence，精确对象和 artifact 读取写入 source-verified evidence，并把命中节点映射到当前 TaskWorkingSet。接口和能力边界见 [Unity ACI 第一层](unity-aci.md)。编译和运行时验证仍必须由后续执行/验证层提供。
