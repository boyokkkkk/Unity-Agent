# SkillGameAgent

SkillGameAgent 是面向 Unity 项目级代码修改实验的 Agent 框架，研究重点是 Unity 代码-资产联合理解、影响范围定位、结构化 Skill 迁移，以及 Compile/Test/PlayMode 验证闭环。

当前项目已经将 mini-SWE-agent 2.4.6 的核心控制框架复现在 `src/game_agent/framework/` 下，运行时不再依赖外部 `minisweagent` 包。

## 1. 当前状态

| 模块 | 状态 | 说明 |
|---|---|---|
| Agent 控制循环 | 已完成 | 本地 `DefaultAgent`，支持轮数、成本、时间和格式错误限制 |
| 本地命令环境 | 已完成 | 本地 `LocalEnvironment`，支持 bash 工具调用和提交检测 |
| 模型适配 | 已完成 | 本地 `LitellmModel`，当前默认模型为 `openai/gpt-4o-mini` |
| Unity 适配 | 已完成基础版 | 校验 Unity 项目、限制工具格式、记录实验事件 |
| CLI | 已完成 | 支持自然语言任务和固定实验配置 |
| 实验日志 | 已完成基础版 | 输出 `events.jsonl` 和 `trajectory.json` |
| Unity 项目图 | 待实现 | Scene、Prefab、GameObject、Component、C# 符号和序列化引用 |
| Verified Skill | 待实现 | Skill 抽取、匹配、迁移和负迁移控制 |
| Compile/Test/PlayMode 验证器 | 待实现 | 当前由 Agent 自行执行命令，尚未形成统一验证接口 |
| FastAPI 后端 | 已完成 MVP | RunManager、Worker 子进程、SQLite、REST/SSE、取消与 artifact API |
| React 前端 | 已完成 MVP | 新建任务、实验列表、SSE 时间线、工具输出、diff、验证与错误/空状态 |

当前执行链路：

```text
CLI
 → load_config
 → LitellmModel
 → DefaultAgent
 → KitchenEnvironment
 → bash
 → Unity 项目
 → events.jsonl / trajectory.json
```

## 2. 环境要求

当前 CLI 运行需要：

- Windows；
- Python 3.10+；
- 可用的大模型 API Key；
- Kitchen Chaos 或其他 Unity 项目；
- 真实执行 Compile、EditMode Test 或 PlayMode Test 时需要 Unity Editor。

默认实验目标为 Kitchen Chaos，原始实验使用 Unity 2021.3.45f1c1。Unity Editor 不需要加入 `PATH`，后续验证器可以使用绝对路径调用。

Web 控制台落地后还需要：

- Node.js；
- npm；
- FastAPI 和 Uvicorn；
- React、TypeScript 和 Vite。

## 3. 首次安装

在本仓库根目录执行。仓库不提交虚拟环境，需要首次运行时创建：

```powershell
py -3.12 -m venv .venv

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

如果系统没有 `py`，可将第一条命令替换为本机 Python：

```powershell
python -m venv .venv
```

验证安装：

```powershell
$env:PYTHONPATH="src"

.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m game_agent --help
```

不必激活虚拟环境，直接调用 `.venv\Scripts\python.exe` 可以避免 PowerShell ExecutionPolicy 对 `Activate.ps1` 的影响。

## 4. 运行前配置

默认配置文件是 [configs/kitchen_chaos.json](configs/kitchen_chaos.json)。首次运行前必须检查以下路径：

```json
{
  "experiment": {
    "target_project": "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos"
  },
  "environment": {
    "cwd": "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos"
  },
  "logging": {
    "events_path": "D:/path/to/Unity-Agent/artifacts/kitchen-chaos/events.jsonl",
    "trajectory_path": "D:/path/to/Unity-Agent/artifacts/kitchen-chaos/trajectory.json"
  }
}
```

要求：

- `experiment.target_project` 和 `environment.cwd` 指向同一个 Unity 项目；
- Unity 项目中必须存在 `ProjectSettings/ProjectVersion.txt`；
- 日志路径必须是当前机器可写路径；
- API Key 只能通过环境变量提供，不能写入 JSON 或提交到 Git。

OpenAI 兼容模型示例：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:PYTHONPATH="src"
```

更换模型时，同时修改配置中的 `model.model_name` 和对应提供商环境变量。

## 5. 最新 CLI 运行方式

运行默认 mini 模式：

```powershell
$env:PYTHONPATH="src"
$env:OPENAI_API_KEY="你的 API Key"

.\.venv\Scripts\python.exe -m game_agent `
  --mode mini `
  --config configs\kitchen_chaos.json `
  --task "检查玩家拾取物品逻辑，修复问题并运行相关 Unity 测试"
```

CLI 参数：

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

`mini` 模式必须提供 `--task`。Agent 完成任务时必须执行：

```text
echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT
```

只有检测到该提交标记时，CLI 才以成功状态退出。达到轮数、成本、时间限制或发生异常时会以失败状态退出。

`fixture` 是旧版本地回归入口。当前工作区已经不包含 `baseline/Unity2D`，因此它不是最新可运行方式；只有恢复对应基线项目后才能使用 `configs/week1.json`。

## 6. Agent 运行过程

一次任务的实际过程如下：

1. `game_agent.cli` 解析参数并定位配置文件；
2. `load_config` 校验实验、模型、环境、Agent 和日志配置；
3. 为本次任务生成 `run_id` 并写入 `run_start`；
4. `get_model` 创建本地 `LitellmModel`；
5. `KitchenEnvironment` 校验 Unity 项目；
6. `get_agent` 创建本地 `DefaultAgent`；
7. Agent 渲染 system prompt 和任务 prompt；
8. 模型返回 bash tool call；
9. Environment 在 Unity 项目目录执行命令；
10. 命令及输出写入 `tool_start/tool_end`；
11. 输出作为 observation 返回模型，进入下一轮；
12. 每轮结束都保存 trajectory；
13. 检测到提交标记后写入最终 trajectory 和 `run_end`。

核心循环：

```text
Model.query(messages)
 → parse bash action
 → Environment.execute(action)
 → observation
 → append messages
 → save trajectory
 → next step or submit
```

Agent 当前拥有本地 shell 能力。任务提示要求它不修改以下 Unity 生成目录：

```text
Library
Temp
Logs
obj
```

建议允许修改的范围：

```text
Assets
Packages
ProjectSettings
```

Web 服务落地前必须增加服务端路径白名单，不能只依赖提示词约束。

## 7. 实验配置与产物

默认实验变量：

| 配置项 | 当前值 |
|---|---|
| Agent 后端 | `skill-game-agent-framework-2.4.6-local` |
| 模型 | `openai/gpt-4o-mini` |
| 工具 | `bash` |
| 温度 | `0.0` |
| 最大输入上下文 | `12000` tokens |
| 单次最大输出 | `2048` tokens |
| 最大总 Token | `81920` |
| 最大 Agent 轮数 | `40` |
| 成本上限 | `3.0` |
| 随机种子 | `42` |

主要产物：

```text
events.jsonl       稳定格式的实验事件
trajectory.json    完整消息、工具调用、成本和退出状态
```

当前事件：

```text
run_start
tool_start
tool_end
run_end
```

后端落地时需要补充：

```text
model_start
model_end
validation_start
validation_end
run_cancelled
artifact_created
```

目标目录结构改为每次运行独立保存：

```text
artifacts/
└── {run_id}/
    ├── events.jsonl
    ├── trajectory.json
    ├── result.json
    ├── diff.patch
    └── validation/
```

## 8. Unity 验证计划

验证闭环分为：

1. C# 编译；
2. EditMode Test；
3. PlayMode Test；
4. PlayMode 状态断言；
5. 必要时增加日志或截图验证。

目标统一接口：

```python
ValidationResult(
    validator="playmode",
    status="passed",
    duration_ms=12000,
    command=[...],
    stdout="...",
    artifact_paths=[...],
)
```

没有安装 Unity Editor 时，状态必须记录为 `skipped_unavailable`，不能记为通过。

第一阶段优先实现：

- Unity Editor 可执行文件探测；
- batchmode Compile；
- EditMode Test；
- PlayMode Test；
- XML 测试报告解析；
- 超时和子进程回收。

## 9. Web 总体架构计划

目标架构：

```text
React + TypeScript + Vite
          │ REST + SSE
          ▼
FastAPI API
          │
          ▼
RunManager
          │ create/cancel/monitor
          ▼
独立 Agent Worker 进程
          │
          ├── SkillGameAgent framework
          ├── Unity workspace
          ├── SQLite
          └── artifacts/{run_id}
```

核心原则：

- HTTP 请求不能直接运行 Agent；
- 一个 Agent 对应一个独立 Worker 进程；
- 后端负责状态持久化、取消、超时和事件转发；
- 浏览器不直接访问 Unity 项目文件；
- API Key 只存在于后端进程环境；
- 首版只监听 `127.0.0.1`；
- 同一个 Unity 工作区同一时间只允许一个写任务；
- 并发实验使用项目副本或 Git worktree。

## 10. FastAPI MVP

阶段 2 已实现，运行方式和完整 API 见 [docs/fastapi-mvp.md](docs/fastapi-mvp.md)。以下目录与接口继续作为后续增强目标。

### 10.1 目标目录

```text
src/game_agent/
├── api/
│   ├── app.py
│   ├── routes/
│   │   ├── runs.py
│   │   ├── configs.py
│   │   └── projects.py
│   └── schemas.py
├── services/
│   ├── run_manager.py
│   ├── run_service.py
│   ├── event_stream.py
│   └── workspace_service.py
├── persistence/
│   ├── database.py
│   └── repositories.py
├── validators/
└── framework/
```

### 10.2 API 设计

```text
POST   /api/runs
GET    /api/runs
GET    /api/runs/{run_id}
POST   /api/runs/{run_id}/cancel
GET    /api/runs/{run_id}/events
GET    /api/runs/{run_id}/trajectory
GET    /api/runs/{run_id}/diff
GET    /api/runs/{run_id}/artifacts
GET    /api/configs
POST   /api/configs/validate
GET    /api/projects/inspect
```

`POST /api/runs` 请求示例：

```json
{
  "task": "修复订单完成后 UI 没有刷新的问题",
  "config_path": "configs/kitchen_chaos.json",
  "project_path": "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos"
}
```

运行状态：

```text
pending
running
submitted
failed
cancelled
timed_out
```

### 10.3 任务执行

MVP 使用独立子进程或 `multiprocessing` Worker：

```text
FastAPI
 → RunManager.create()
 → 创建 run_id 和 artifact 目录
 → 启动 Worker
 → Worker 调用 game_agent.mini.run()
 → 读取 events.jsonl
 → SSE 推送浏览器
```

不要用 FastAPI 请求线程直接执行 Agent。取消任务时，RunManager 必须终止整个进程树，并将状态持久化为 `cancelled`。

### 10.4 数据持久化

首版使用 SQLite，不引入 Redis、PostgreSQL 或 Celery。

建议表：

```text
runs
run_events
artifacts
experiment_configs
projects
skills
skill_applications
validations
```

`events.jsonl` 保留为可移植实验原始记录，SQLite 用于 UI 查询；两者不能互相替代。

### 10.5 后端开发指令

后端实现完成后，依赖应加入 `pyproject.toml`，预期开发指令为：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[web]"

.\.venv\Scripts\python.exe -m uvicorn game_agent.api.app:app `
  --reload `
  --host 127.0.0.1 `
  --port 8000
```

以上命令属于目标运行方式；当前仓库尚未包含 `game_agent.api.app` 和 `web` optional dependency。

## 11. React 实验控制台

阶段 3 已实现，开发与前后端契约见 [docs/frontend-console.md](docs/frontend-console.md)。以下内容保留为后续增强计划。

### 11.1 技术栈

- React；
- TypeScript；
- Vite；
- 原生 Fetch 或轻量请求封装；
- SSE 接收单向事件流；
- 后续项目图使用独立图可视化组件。

首版不需要 Next.js、服务端渲染或复杂状态管理框架。

### 11.2 页面

```text
/runs                 实验历史
/runs/new             创建任务
/runs/:runId          运行时间线
/runs/:runId/result   diff、验证和产物
/configs              配置管理
/projects             Unity 项目检查
/graph                Unity 项目图，第二阶段
/skills               Verified Skill，第三阶段
```

运行详情页至少显示：

- 当前状态和耗时；
- 模型调用次数、Token 和成本；
- Agent 消息；
- bash 命令、返回码和输出；
- Compile/Test/PlayMode 状态；
- 最终提交内容；
- 修改 diff；
- trajectory 和日志下载入口。

### 11.3 前端开发指令

前端目录创建后：

```powershell
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm run dev
```

生产构建：

```powershell
npm run build
npm run preview
```

开发环境默认约定：

```text
Frontend: http://127.0.0.1:5173
Backend:  http://127.0.0.1:8000
API:      http://127.0.0.1:8000/api
```

Vite 开发服务器通过代理访问 `/api`，避免在前端硬编码后端地址。

## 12. 分阶段交付计划

### 阶段 1：稳定 Headless Agent

交付物：

- 当前本地 framework；
- 配置路径校验；
- 每次运行独立 artifact 目录；
- model/validation 事件；
- 统一退出状态；
- Agent 与 Environment 单元测试。

验收标准：

- CLI 可以连续运行三个任务；
- 任意失败均产生完整 `run_end`；
- 不同运行不会覆盖日志；
- 无 Unity Editor 时验证状态正确。

### 阶段 2：FastAPI MVP

交付物：

- RunManager；
- Worker 子进程；
- SQLite；
- 创建、查询、取消任务 API；
- SSE 事件流；
- trajectory、diff 和 artifact API。

验收标准：

- HTTP 请求立即返回 `run_id`；
- 刷新页面后仍可查询任务；
- 可以取消运行中的 Agent；
- 后端重启后仍能读取历史记录。

### 阶段 3：React 实验控制台

交付物：

- 新建任务页面；
- 实验列表；
- 实时时间线；
- 工具输出查看器；
- diff 和验证结果；
- 错误与空状态。

验收标准：

- 不打开终端即可创建和观察任务；
- 事件断线后能够从最后序号恢复；
- 大段命令输出不会阻塞页面；
- 桌面和移动端均可使用。

### 阶段 4：Unity 项目图

交付物：

- Editor API 导出器；
- C# 和资产联合图；
- SQLite/NetworkX 存储；
- 影响范围 API；
- 图查询与可视化；
- Recall@K 评测。

### 阶段 5：Verified Skill

交付物：

- Skill Schema；
- 成功轨迹抽取；
- 图前置条件匹配；
- 文本 Skill 与 Graph Skill 对照；
- 失败模式和负迁移记录；
- Skill 管理 UI。

### 阶段 6：完整实验与部署

交付物：

- A0/A1/A2 定位实验；
- A2-T/A2-S/A2-G 迁移实验；
- Compile/Test 与 PlayMode 消融；
- 成本和统计报表；
- 前端静态构建；
- 本地一键启动脚本；
- 演示数据和答辩流程。

## 13. 安全与并发要求

Web 化之后必须实现：

- Unity 项目根目录白名单；
- 禁止访问白名单外路径；
- 禁止修改 `Library/Temp/Logs/obj`；
- API Key 脱敏；
- 命令、输出和异常审计；
- 单任务成本、时间和轮数限制；
- Worker 进程树回收；
- 单工作区写锁；
- artifact 下载路径校验；
- 默认只允许本机访问。

当前 `KitchenEnvironment` 只校验 action 格式，没有真正的命令级沙箱。项目对外部署前必须补齐隔离，不能直接把当前 bash 工具暴露到公网。

## 14. 目标一键运行方式

完整 Web 版本落地后的目标命令：

终端一：

```powershell
$env:OPENAI_API_KEY="你的 API Key"
$env:PYTHONPATH="src"

.\.venv\Scripts\python.exe -m uvicorn game_agent.api.app:app `
  --host 127.0.0.1 `
  --port 8000
```

终端二：

```powershell
cd frontend
npm install
npm run dev
```

最终再提供统一脚本：

```powershell
.\scripts\start-dev.ps1
```

生产演示版由 FastAPI 托管 `frontend/dist`，只启动一个本地端口。

## 15. 开发入口

核心代码：

```text
src/game_agent/framework/agents/default.py
src/game_agent/framework/environments/local.py
src/game_agent/framework/models/litellm_model.py
src/game_agent/mini.py
src/game_agent/cli.py
src/game_agent/logging.py
```

职责：

- `framework/agents/default.py`：Agent 控制循环；
- `framework/environments/local.py`：命令执行；
- `framework/models/litellm_model.py`：模型与工具调用；
- `mini.py`：Unity 项目适配和实验组装；
- `cli.py`：命令行入口；
- `logging.py`：稳定 JSONL 事件。

`references/mini-SWE-agent` 仅作为只读上游参考，不是运行时依赖。

## 16. 常见问题

### 找不到 `game_agent`

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m game_agent --help
```

### PowerShell 无法激活虚拟环境

不需要执行 `Activate.ps1`，直接使用：

```powershell
.\.venv\Scripts\python.exe
```

### 缺少依赖

```powershell
.\.venv\Scripts\python.exe -m pip install -e .
```

### API Key 错误

确认模型提供商对应的环境变量已设置，并且没有把 Key 写入配置文件。

### Unity 项目路径错误

确认：

```text
<UNITY_PROJECT>/ProjectSettings/ProjectVersion.txt
```

存在，并确保 `target_project` 与 `environment.cwd` 一致。

### Agent 修改了不应修改的文件

检查 `trajectory.json` 和 `events.jsonl` 定位具体命令。当前提示词只提供软约束；Web 后端落地时还必须增加路径白名单、工作区锁和进程隔离。
