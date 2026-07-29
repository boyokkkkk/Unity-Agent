# Unity research benchmark

## Run a matrix

Copy `configs/benchmark.example.json`, replace the Unity project path, and configure the required provider keys. Preview the Cartesian product without starting an Agent:

```powershell
game-agent-benchmark --manifest configs/benchmark.example.json --dry-run
```

Execute it with the manifest's concurrency setting:

```powershell
game-agent-benchmark --manifest configs/benchmark.example.json
```

The matrix is `tasks × models × skills × seeds`. Every case receives a deterministic ID derived from the complete task, model, Skill, seed, project, and base-config inputs. A changed model parameter therefore creates a new case instead of incorrectly reusing an old result.

## Progress, retries, and resume

The runner writes `progress.json` atomically after every completed case. Successful cases are skipped on resume. Failed cases are rerun when `retry_failed_on_resume` is true. `retries: 1` means one initial attempt plus one retry.

Use `--no-resume` to start a new pass in the same output directory. Attempt directories are append-only (`attempt-001`, `attempt-002`, and so on), so previous evidence is not overwritten.

Each case runs in its own spawned Python process through the P0 isolated Unity Worker, so model counters and process-global limits do not leak between matrix cells. Parallel cases also use separate Git worktrees or filtered copies. The original Unity project is not modified.

## Metrics and artifacts

The benchmark directory contains:

```text
progress.json
results.json
summary.json
results.csv
cases/{case_id}/attempt-{number}/
```

Metrics are reported overall and grouped by model, Skill, seed, and their combination:

- benchmark success and success rate;
- Agent submission success separately from Unity-verified success;
- passed, failed, missing, disabled, and `skipped_unavailable` validation counts;
- total and mean cost, tokens, model calls, rounds, and duration.

Retry resource usage is accumulated, not discarded. For example, the cost of a failed first attempt and successful second attempt both contribute to the case and aggregate totals.

## Model variants

Controlled model aliases are:

```text
litellm
litellm_response
responses
openrouter
openrouter_response
```

`litellm` and `openrouter` use chat-completions-style tool calls. `litellm_response`/`responses` and `openrouter_response` use the flat Responses tool schema and return `function_call_output` observations linked by `call_id`.

OpenRouter chat requests use `https://openrouter.ai/api/v1/chat/completions`. Its Responses adapter uses `https://openrouter.ai/api/v1/responses`, replays the complete history, and does not rely on server-side state. Set `OPENROUTER_API_KEY` in the Worker environment.

## Controlled components

List the active allow-list:

```powershell
game-agent-benchmark --list-components
```

Manifests contain registry aliases only. Values such as `package.module.Class` are rejected; the runner never imports a module path supplied by a manifest. Extensions must explicitly register a callable under one of the supported component kinds before execution.
