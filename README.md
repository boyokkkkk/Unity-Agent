# SkillGameAgent

SkillGameAgent 是面向 Unity 项目级代码修改实验的 Agent 框架。当前默认基于 mini-SWE-agent 2.4.6，目标游戏项目为：

```text
E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos
```

Agent 使用 mini-SWE-agent 的完整执行链路：

```text
Model → DefaultAgent → KitchenEnvironment → bash → Unity 项目
                                      ↓
                              Compile / Test / Submit
```

## 1. 环境要求

- Windows
- Python 3.10+
- 项目自带虚拟环境：`.venv`
- mini-SWE-agent 2.4.6
- Kitchen Chaos Unity 项目
- 已配置可用的大模型 API Key
- 如果需要真实 Compile、EditMode Test 或 PlayMode Test，还需要安装 Unity Editor

当前 Kitchen Chaos 项目版本为 Unity 2021.3.45f1c1。Unity Editor 不要求加入系统 PATH，可以在配置中填写 Unity 可执行文件的绝对路径。

## 2. 默认运行方式

在项目根目录 `E:\sysu-course\GameAgent` 执行：

```powershell
$env:PYTHONPATH="src"
$env:OPENAI_API_KEY="你的 API Key"

.\.venv\Scripts\python.exe -m game_agent `
  --task "检查玩家拾取物品逻辑，修复问题并运行相关 Unity 测试"
```

也可以先设置模型提供商对应的环境变量，再运行 Agent。例如使用 LiteLLM 支持的模型：

```powershell
$env:PYTHONPATH="src"
$env:OPENAI_API_KEY="你的 API Key"
$env:MSWEA_SILENT_STARTUP="1"

.\.venv\Scripts\python.exe -m game_agent `
  --task "修复厨房游戏中订单完成后 UI 没有刷新的问题"
```

`--task` 接收自然语言任务。Agent 会自行检查项目、定位文件、修改代码、运行验证，并在完成后执行：

```text
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

## 3. CLI 参数

```text
--mode {mini,fixture}
--config CONFIG
--task TASK
```

默认值：

```text
--mode mini
--config configs/kitchen_chaos.json
```

mini 模式必须提供 `--task`：

```powershell
.\.venv\Scripts\python.exe -m game_agent `
  --mode mini `
  --config configs\kitchen_chaos.json `
  --task "检查并修复玩家移动逻辑"
```

## 4. 固定实验配置

默认配置文件为 [configs/kitchen_chaos.json](configs/kitchen_chaos.json)，其中固定了实验变量：

| 配置项 | 当前值 |
|---|---|
| Agent 后端 | mini-SWE-agent 2.4.6 |
| 模型 | `openai/gpt-4o-mini` |
| 工具 | `bash` |
| 温度 | `0.0` |
| 最大输入上下文 | `12000` tokens |
| 单次最大输出 | `2048` tokens |
| 最大总 Token | `81920` |
| 最大 Agent 轮数 | `40` |
| 成本上限 | `3.0` |
| 随机种子 | `42` |

配置校验会阻止工具、轮数和成本限制被意外改成不一致的值。API Key 通过环境变量提供，不写入配置文件。

## 5. Agent 工具与工作目录

Agent 当前只暴露 mini-SWE-agent 的 `bash` 工具。所有命令默认在以下目录执行：

```text
E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos
```

任务提示中禁止修改以下 Unity 生成目录：

```text
Library
Temp
Logs
obj
```

建议 Agent 只修改：

```text
Assets
Packages
ProjectSettings
```

实际任务中仍应要求 Agent 先阅读相关脚本和场景，再进行最小修改，并运行针对性验证。

## 6. 日志和 trajectory

默认输出目录：

```text
E:\sysu-course\GameAgent\artifacts\kitchen-chaos\
```

主要文件：

```text
events.jsonl       固定格式的实验事件日志
trajectory.json    mini-SWE-agent 原生轨迹文件
```

日志使用 `game-agent-jsonl-v1` 格式，每行一个 JSON 事件。主要事件包括：

```text
run_start
tool_start
tool_end
run_end
```

每条记录包含：

```text
schema_version
ts
run_id
config_id
seq
event
```

`tool_start` 和 `tool_end` 会记录 bash 命令、返回码、输出和异常信息。即使 Agent 通过提交命令提前结束，两个事件也会成对写入。

## 7. Fixture 回归模式

旧版本地 fixture 基线仍然保留，用于验证 Agent 框架自身的文件读写、Compile、Test 和日志功能，不会操作 Kitchen Chaos：

```powershell
$env:PYTHONPATH="src"

.\.venv\Scripts\python.exe -m game_agent `
  --mode fixture `
  --config configs\week1.json
```

fixture 结果写入：

```text
artifacts\week1-summary.json
artifacts\logs\events.jsonl
```

## 8. Unity 验证

Unity Editor 相关命令需要在配置中指定 Unity 可执行文件。例如：

```json
{
  "unity": [
    "C:/Program Files/Unity/Hub/Editor/2021.3.45f1c1/Editor/Unity.exe",
    "-batchmode",
    "-quit",
    "-projectPath",
    "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos"
  ]
}
```

Unity 验证建议分为：

1. C# 编译验证；
2. EditMode Test；
3. PlayMode Test；
4. 必要时增加状态日志或截图验证。

没有 Unity Editor 时，不应将 PlayMode 结果记为通过，应记录为 unavailable 或 skipped。

## 9. 开发入口

核心适配层位于：

```text
src/game_agent/mini.py
```

其中：

- `KitchenEnvironment` 继承 mini-SWE-agent 的 `LocalEnvironment`；
- `get_model` 创建 mini-SWE-agent 模型；
- `get_agent` 创建 mini-SWE-agent `DefaultAgent`；
- `agent.run(task)` 执行完整 Agent 循环；
- `agent.save(...)` 保存原生 trajectory。

如需加入科研创新点，应优先在该适配层增加：

- Unity 项目结构分析；
- Scene/GameObject/Component/Prefab 关系抽取；
- 影响范围定位；
- Graph-Conditioned Skill；
- Compile/Test/PlayMode 验证器。

不要直接修改 `references/mini-SWE-agent` 中的第三方源码。

## 10. 常见问题

### 找不到 `game_agent`

确认已设置：

```powershell
$env:PYTHONPATH="src"
```

### 找不到 mini-SWE-agent

使用项目虚拟环境：

```powershell
.\.venv\Scripts\python.exe -m game_agent --help
```

### API Key 错误

检查对应模型提供商的环境变量，例如：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
```

### Unity 项目路径错误

确认以下文件存在：

```text
E:\Unity_project\Kitchen_Chaos\Kitchen_Chaos\ProjectSettings\ProjectVersion.txt
```

### Agent 修改了不应修改的文件

检查 trajectory 和 `events.jsonl`，定位具体 bash 命令。当前提示词要求不修改 `Library`、`Temp`、`Logs` 和 `obj`；后续可进一步增加命令级路径白名单。
