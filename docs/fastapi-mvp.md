# FastAPI MVP

## Run locally

Install the Web optional dependencies and start the API from the repository root:

```powershell
python -m pip install -e ".[web]"
$env:GAME_AGENT_DATA_DIR="artifacts"
python -m uvicorn game_agent.api.app:app --host 127.0.0.1 --port 8000
```

`GAME_AGENT_DATA_DIR` defaults to `artifacts`. SQLite is stored at
`artifacts/game-agent.db`; each run owns `artifacts/runs/{run_id}/`.

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/runs` | Create a worker run and immediately return its record |
| `GET` | `/api/runs` | List persisted runs |
| `GET` | `/api/runs/{run_id}` | Read one run |
| `POST` | `/api/runs/{run_id}/cancel` | Terminate the worker process tree |
| `GET` | `/api/runs/{run_id}/events` | Stream persisted events with SSE |
| `GET` | `/api/runs/{run_id}/events/history` | Read persisted event history as JSON |
| `GET` | `/api/runs/{run_id}/trajectory` | Read trajectory JSON |
| `GET` | `/api/runs/{run_id}/diff` | Read the Git patch captured after the run |
| `GET` | `/api/runs/{run_id}/artifacts` | List artifacts |
| `GET` | `/api/runs/{run_id}/artifacts/{name}` | Download one artifact |

Create request:

```json
{
  "task": "??????? UI ???????",
  "config_path": "configs/kitchen_chaos.json",
  "project_path": "E:/Unity_project/Kitchen_Chaos/Kitchen_Chaos"
}
```

The project path must contain `ProjectSettings/ProjectVersion.txt`. Only one active
write run is allowed for a given Unity project. Use a project copy or Git worktree
for concurrent experiments.

## SSE recovery

SSE event IDs are SQLite event IDs. Reconnect with either:

```text
Last-Event-ID: 42
```

or `GET /api/runs/{run_id}/events?after=42`. Worker JSONL events are ingested into
SQLite while the process is running, so browser refreshes do not lose event history.

## Lifecycle and artifacts

Run states are `pending`, `running`, `submitted`, `failed`, `cancelled`, and
`timed_out`. The current worker uses the first five; `timed_out` is reserved for the
RunManager-level timeout policy.

Typical files:

```text
artifacts/runs/{run_id}/
??? config.json
??? events.jsonl
??? trajectory.json
??? result.json
??? diff.patch
```

Artifact download paths are resolved beneath the run directory and reject path
traversal. The service is intended to listen on `127.0.0.1`; do not expose the
current unrestricted shell worker directly to a public network.
