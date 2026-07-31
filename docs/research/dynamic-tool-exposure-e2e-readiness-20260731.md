# 动态工具暴露与真实模型 E2E 准入

日期：2026-07-31

## 三套最小工具集合

所有 profile 均保留协议核心工具 `powershell` 与 `submit`；表中的数量包含这两个核心工具。

| Profile | ACI 工具 | 总工具数 |
|---|---|---:|
| localization | `code_symbol_search`, `unity_asset_search`, `code_find_references`, `code_file_read`, `artifact_read` | 7 |
| implementation-script | 精确读取、引用、diagnostics、artifact，加 `unity_script_patch` | 9 |
| implementation-asset | 精确读取、引用、diagnostics、artifact，加 typed asset mutations | 17 |
| validation | `code_diagnostics`, `unity_recompile`, `unity_hot_reload`, `unity_validate`, `artifact_read` | 7 |

选择规则：

- `localized_target` 或 `implementation_source` 尚未解决时使用 localization；
- 两个证据槽均已解决后，根据 working-set 路径选择 script/asset mutation；
- 一旦 mutation 创建 pending checkpoint，无条件锁定 validation profile；
- validation 锁定持续到 diagnostics、reload policy 和全部 required validation modes 完成。

`unity_execute_csharp` 不进入默认最小集合，它仍保留在完整工具注册表中，作为显式关闭动态暴露时的 escape hatch。

## Schema token 记录

每次模型调用前的 `model_preflight` 记录：

- `tool_profile`;
- `exposed_tool_names` 与 `exposed_tool_count`;
- `tool_schema_tokens`;
- `validation_tools_locked`;
- `dynamic_tool_exposure_applied`。

StageAnalyzer 汇总每个 profile 的调用次数与 schema token。以当前
`openai/qwen-plus` 本地 estimator 为例：

| 协议 | 全量 | localization | implementation-script | implementation-asset | validation |
|---|---:|---:|---:|---:|---:|
| Chat Completions | 5498 | 1282 | 1568 | 3435 | 931 |
| Responses conservative estimate | 15072 | 3484 | 4268 | 9444 | 2521 |

这些数值用于同一协议内的相对比较；不同协议的 estimator 口径不同，不应直接比较绝对值。

## 真实模型 E2E 准入判断

代码侧已满足准入条件：

- 动态 schema 同时覆盖 LiteLLM/OpenRouter 的 Chat 与 Responses 协议；
- mutation 后 validation profile 强制可见；
- schema token 能逐调用记录并按 profile 汇总；
- 本地 targeted tests 已通过。

当前机器尚不应立即启动付费真实模型 E2E，环境检查仍有两个硬阻塞：

1. 未发现 Unity `2021.3.45f1c1` Editor，`UNITY_EDITOR_PATH` 也未配置；
2. 当前进程未发现 DashScope/OpenAI/LiteLLM 模型凭据。

其余条件已满足：Kitchen Chaos 工程与 Git 仓库存在、没有 `UnityLockfile`，完整项目图存在，
且 `configs/kitchen_chaos.json` 会由启动器相对配置仓库正确解析图路径。

解除两个硬阻塞后，建议先运行一个已知缺陷的单任务 smoke E2E；只有在真实请求中确认
`localization -> implementation -> validation` profile 转换、schema token 记录和验证门禁均正常，
再启动完整真实模型矩阵。
