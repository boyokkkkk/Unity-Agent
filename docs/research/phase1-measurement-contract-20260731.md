# 第一阶段测量闭环契约

日期：2026-07-31

## 范围

本阶段只建立可复现的测量闭环，不改变图检索排序、重复动作门控策略或动态工具暴露策略。

ACI 查询、mutation 和 validation 在 Agent 动作边界统一发出 `tool_start` / `tool_end`。这样，Controller 执行前被重复动作门控拦截的调用也不会从统计中消失。

## 标准 ACI 事件

每个事件至少保留：

- `tool`、`tool_call_id`、`tool_class`
- `arguments_hash`、`action_signature`
- `node_ids`、`changed_paths`、`accessed_files`
- `evidence_ids`
- `returncode`、`blocked`、`blocked_reason`

`tool_start` 还记录调用前可用证据、引用节点和失效节点；`tool_end` 记录输出摘要、证据写入预期和执行协议状态。原始参数不写入 telemetry，避免大参数或敏感值扩散；动作比较使用规范化参数的 SHA-256。

## 旧轨迹回放

当事件流没有原生 ACI telemetry 时，StageAnalyzer 从 trajectory 的 assistant actions 和 tool observations 重建事件对。若已存在原生 ACI 事件，则不回放，防止重复计数。

回放必须保持以下回归事实：

- 前两次相同 `code_file_read` 计为成功执行；
- 第三次计为 `returncode=-2`、`blocked=true`；
- 三次共享相同 `action_signature`，因此重复动作比率为 `2/3`。

## 指标解释

Stage metrics schema 升级为 `game-agent-stage-metrics-v2`，新增 `research`：

- `retrieval`：Top-4 路径多样性、测试节点占比、根因 MRR、因果边覆盖；
- `memory`：证据写入、下一轮呈现、证据利用和失效证据；
- `control`：重复动作、blocked 后恢复、可接受动作采用、阶段回退和协议完成；
- `tools_and_cost`：ACI 调用数、每轮 schema tokens、单位 token 新证据、typed mutation 与 escape hatch。

所有比率同时提供关键分母或机会数。分母为零时比率定义为 `0.0`，调用方必须结合对应的 `*_opportunities`、`*_total` 或 `*_measurements` 判断它表示“没有发生”还是“尚不可测”。

