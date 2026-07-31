# 证据到动作编译器契约

日期：2026-07-31

## 状态

控制器对模型暴露以下最小状态：

- `completed_actions`：成功执行的动作、结论、结果 SHA 和 evidence IDs；
- `disabled_actions`：当前不可再次执行的签名及原因；
- `unresolved_slots`：仍需补齐的定位、实现读取或验证证据；
- `admissible_action_signatures`：最近一次 replan 给出的可接受动作；
- `replan_count`。

这些字段同时进入 trajectory 的 ACI state 和每轮 virtual context。

## `code_file_read` 签名

读取签名为：

`code_file_read:<normalized path>:<requested range>:<current file sha256>`

因此：

- 同一路径、同一范围、同一 SHA：成功后 disabled；
- 同一路径、不同范围：新动作，允许执行；
- 文件内容变化、产生新 SHA：新动作，允许执行；
- 失败读取：只记录 unresolved failure，不进入 completed/disabled。

## 结构化 replan

重复或 disabled 动作返回 `status=replan`，而不是立即终止 Agent。响应必须包含：

- `location`；
- `observed`；
- `blocked_action` 与 `blocked_reason`；
- `unresolved_slots`；
- 1–3 个 `admissible_next_actions`。

候选动作只能来自已观测的文件范围、项目图 working set 或已有节点引用，不直接指定最终补丁。
若模型继续无视 alternatives，原有 step/no-progress 限制仍提供最终有界终止。

