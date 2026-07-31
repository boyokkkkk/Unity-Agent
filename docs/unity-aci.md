# Unity ACI 第一层：结构化查询接口

当前线性 Agent 已接入只读 Unity Agent-Computer Interface。模型仍负责选择下一步，但定位、图遍历、对象读取和 artifact 分页不再需要构造 PowerShell 命令。

## 接口

| 工具 | 数据源 | P1 更新 |
|---|---|---|
| `unity_editor_status` | ProjectSettings、Editor 安装与实例信息 | observation evidence |
| `unity_asset_search` | ProjectGraph 节点索引 | WorkingSet + observation evidence |
| `unity_ref_search` | ProjectGraph 有向边、多跳 BFS | WorkingSet + observation evidence |
| `unity_object_list` | GAME_OBJECT/COMPONENT 节点 | WorkingSet + observation evidence |
| `unity_object_search` | 对象名称、层级、类型和路径 | WorkingSet + observation evidence |
| `unity_object_read` | 节点详情、组件和一跳关系 | WorkingSet + source-verified evidence |
| `code_symbol_search` | CSHARP_FILE/TYPE/METHOD/FIELD 节点 | WorkingSet + observation evidence |
| `code_find_references` | CALLS、UNITY_EVENT_CALL 等图边 | WorkingSet + observation evidence |
| `code_diagnostics` | 图一致性、已有诊断和失效状态 | observation evidence；不冒充 compile |
| `artifact_read` | 当前 run 的 artifact store | source-verified evidence |

模型工具协议同时支持 Chat Completions 和 Responses API。原有 `powershell`、`submit` 保持兼容。

## 统一结果契约

工具 observation 的正文是有界 JSON，执行元数据包含：

```json
{
  "aci": true,
  "query_tool": "unity_object_read",
  "structured": {},
  "node_ids": ["..."],
  "evidence_sources": ["graph:..."],
  "evidence_status": "source_verified",
  "evidence_claim": "...",
  "artifact_path": "tool-outputs/..."
}
```

`DefaultAgent` 执行后立即把 `node_ids` 映射到当前 `TaskWorkingSet`，并把 claim/source/status 写入 `EvidenceLedger`。完整工具输出继续沿用 LocalEnvironment 的 artifact 外置和预览截断策略。

## 配置

模型配置使用：

```json
{
  "structured_query_tools_enabled": true
}
```

历史 baseline 会强制关闭该开关，避免工具 schema token 和行为变化污染对照组。需要项目图的查询还必须配置 `context.graph_path`；未配置时返回 `status: unavailable`，不会生成虚假证据。

## 当前能力边界

- 尚无 Unity Editor bridge，因此 `unity_editor_status` 可以报告项目、Editor 安装和进程线索，但 `editor_state` 明确为 `disconnected`，不能断言 editing/playing。
- 尚无常驻 Roslyn workspace server，因此 `code_diagnostics` 当前只返回项目图一致性和构图阶段已有诊断，`compiler_diagnostics_available=false`、`compile_verified=false`。
- 查询使用构图时的 Unity 对象快照；文件变化由 P1 失效机制标记，重新构图后才能恢复最新资产语义。
- 工具 schema 当前直接注入；后续可增加按阶段或按需加载，降低每轮 schema token。

## 与 Locus 的对应关系

本实现复用了 Locus 的三个关键原则：专用查询优先于 shell、结构化小结果优先于原始文件、控制器负责状态与证据副作用。但没有复制其私有 Editor bridge、Roslyn LSP 或任意 C# 执行能力；这些属于后续 ACI 执行层。

## 第二层：类型化修改接口

Agent 现在优先使用类型化 Unity 修改工具，而不是拼接任意 C#：

- `unity_gameobject_create/delete/rename`
- `unity_component_add/remove`
- `unity_serialized_property_set`
- `unity_prefab_create`
- `unity_asset_save` 与 `unity_asset_import`
- `unity_script_patch`

Scene 和 Prefab 修改由 `GameAgentAciBridge.cs` 在 Unity batchmode 主线程中执行，使用
`Undo`、`SerializedObject`、`PrefabUtility`、`EditorSceneManager` 和 `AssetDatabase`，
并自动保存目标、执行 import/refresh。脚本 patch 使用读取时得到的 SHA-256 和单次精确
文本替换，拒绝在源文件已变化或匹配不唯一时执行；其 AssetDatabase 收敛由随后强制的
`unity_recompile` 完成。

`unity_execute_csharp` 保留为 escape hatch。调用者必须声明全部可能修改的
`target_paths`，控制器会先 checkpoint。Trajectory 中记录
`typed_mutation_calls`、`escape_hatch_calls` 和 `escape_hatch_ratio`；该比例用于发现
类型化接口覆盖不足。

当前 escape hatch 通过临时 Editor helper 和 batchmode 执行，只支持 editing 状态。
真正的低延迟、保持 Play Mode 状态的执行仍需要常驻 Editor bridge。

## 第三层：控制器执行协议

`UnityAciController` 在现有线性 Agent 的 action middleware 中实施以下门控：

1. 修改参数必须携带已有项目图定位证据的 `evidence_node_ids`。
2. 每个目标必须先经 `unity_object_read`、`unity_asset_read` 或 `code_file_read`
   形成 `source_verified` 证据。
3. 控制器在任何写入前把目标文件、`.meta`、摘要和操作写入
   `checkpoints/<checkpoint-id>/manifest.json`。
4. 类型化修改执行后自动 save/import/refresh，并将图节点标记 dirty。
5. 必须调用 `code_diagnostics`；存在静态 error 时阶段不会推进。
6. 脚本变更必须成功执行 `unity_recompile`，或在未来 live bridge 可用时执行
   `unity_hot_reload`。
7. 必须完成配置要求的 EditMode/PlayMode 验证。
8. 验证成功后写入 `EvidenceLedger` 的 `runtime_verified` 证据。

协议未完成时，控制器会阻止新的修改和 `submit`。当前 `unity_hot_reload` 明确返回
unavailable，不会伪造成功；使用 `unity_recompile` 完成磁盘状态收敛。

类型化修改会把受影响图节点标记为 dirty。由于当前图构建仍是离线流程，在重新构图前，
控制器拒绝再次依赖这些旧节点执行修改；这保证安全，但也意味着同一 Scene/Prefab 的
连续多轮修改目前需要在轮次之间刷新项目图。
