# Console Agent and SSE Design

## Objective

Provide two development-focused observability paths for SkillGameAgent:

1. Restore the active React run detail page to a resumable SSE event stream.
2. Add a standalone, lightweight terminal Agent session that exercises the real
   Model-Agent-Environment control loop without starting FastAPI or React.

The terminal experience is intended for rapid Agent debugging and verification.
It is not a full-screen TUI and does not attempt to reproduce every Codex CLI
feature.

## Scope

### Included

- A standalone `game-agent-console` entry point.
- Multiple tasks in one console process.
- Multiple conversational turns in one task with full linear context retention.
- `/new`, `/status`, `/diff`, `/help`, and `/exit` commands.
- Automatic command execution for development.
- Live component-aware output for the run script, Agent, Model, Environment,
  tools, validation, and Skill activity.
- Per-task trajectory, event log, result, diff, and resolved configuration.
- A shared structured event vocabulary used by the console, artifacts, and Web
  event rendering.
- SSE history recovery, event deduplication, reconnect support, and terminal
  result refresh in the active React run detail page.
- Automated tests using fixture models and temporary Unity repositories.

### Excluded

- Full-screen terminal UI, panes, keyboard navigation, themes, or mouse support.
- Interactive command approval in the first version.
- Session branching, session search, or reopening historical console sessions.
- Implementing the future Verified Skill retrieval and execution engine.
- Public-network hardening or a command sandbox.
- A browser end-to-end testing framework.

## Existing Behavior

Each current Web or CLI run creates a new Model, Environment, and
`DefaultAgent`. `DefaultAgent.run()` clears `messages`, adds one system message
and one user task, then appends model and tool observations linearly until an
exit message is produced. Context is complete inside one run but cannot continue
across calls to `run()`.

The active React detail page polls all run resources every 2.5 seconds. An older,
unrouted detail page uses `EventSource`. The backend already persists event IDs
and supports `after` and `Last-Event-ID`, but emits arbitrary event names rather
than one stable envelope event.

The repository has UI representations of Skills but no real Skill runtime.
Console output must never imply that a Skill ran unless the runtime emitted a
real Skill event.

## Architecture

```text
game-agent-console
  -> ConsoleApplication
      -> ConsoleSession
          -> ConsoleTask
              -> ConsoleAgent
                  -> LitellmModel
                  -> KitchenEnvironment
              -> StructuredEventSink
                  -> ConsoleRenderer
                  -> ExperimentLogger
              -> TaskArtifacts

React AgentRunDetailPage
  -> runEventStream
      -> history API
      -> EventSource run_event envelopes
      -> ID-based merge and deduplication
      -> terminal resource refresh
```

The console runs in the foreground in one process. Shell actions remain
independent subprocesses through `LocalEnvironment`. FastAPI, SQLite, and the
React application are not required.

## mini-SWE-agent Component Rotation

The four upstream pieces are the run script, Agent, Model, and Environment.
The observable control flow is:

```text
Run script
  -> construct Agent(Model, Environment)
  -> Agent starts round
  -> Model receives the complete linear message history
  -> Model returns assistant content and/or bash actions
  -> Agent dispatches actions
  -> Environment executes each bash action
  -> Agent appends observations
  -> next round or terminal outcome
  -> Run script saves artifacts
```

Bash is the Environment's only current tool; it is not treated as a fifth
upstream component. Console events expose both the component transition and the
concrete tool execution.

## Console Session Semantics

### Session, Task, Turn, and Round

- A session is one invocation of `game-agent-console`.
- A task is one persistent Agent context.
- A turn is one user input and the Agent work performed before control returns.
- A round is one Model query followed by zero or more Environment actions.

Normal input starts another turn in the current task. `/new` saves the current
task and creates a fresh task, Model, Environment, Agent, and message history.

### Context Continuation

The first turn adds the system message and rendered instance message. Later turns
append a normal user message to the existing linear history. A successful
submission becomes a normal assistant message for future Model requests rather
than leaving an invalid `exit` role in the history.

Per-turn round, wall-time, and cost limits reset at the beginning of each turn.
Task totals for model calls, tool calls, elapsed time, and cost continue to
accumulate. `/new` resets both context and task totals.

Failed turns preserve all valid messages and observations produced before the
failure. Authentication and unrecoverable Model errors return control to the
console so the developer can inspect status or start a new task.

### Commands

```text
/new [optional initial request]
/status
/diff
/help
/exit
```

Unknown slash commands produce a short help message and do not enter the Agent
context. Empty input is ignored.

`Ctrl+C` interrupts the active turn when possible, writes the current task
artifacts, and returns to the prompt. A second interrupt or an interrupt while
idle exits after finalizing the task.

## Console Rendering

Default output is concise and component-prefixed:

```text
[Run]    Turn #1 started
[Agent]  Round 1 | 2 messages | requesting model
[Model]  qwen-plus | 2.4s | 1 bash action
[Skill]  Verified Skill runtime is not enabled
[Env]    bash: rg "OrderComplete" Assets/Scripts
         exit 0 | 18 lines | 0.3s
[Agent]  observation appended | continuing to Round 2
[Model]  final answer
[Run]    Turn #1 completed
```

Rules:

- Print commands, return codes, durations, and bounded output.
- Successful commands with no output print only their success metadata.
- Failed commands print the error and the bounded output tail.
- Never print full raw Model responses or trajectory JSON by default.
- Preserve untruncated data in artifacts.
- At the end of every turn, print the final answer, model/tool counts, elapsed
  time, changed file count, line summary, and diff artifact path.
- At task start, print Skill availability exactly once.
- Do not infer Skill usage from command text, filenames, or event-name
  substring matching.

## Structured Events

The shared vocabulary is:

```text
task_start
task_end
turn_start
turn_end
agent_round_start
agent_observation_added
agent_limit_reached
model_start
model_end
model_error
skill_search_start
skill_matched
skill_not_found
skill_apply_start
skill_apply_end
skill_apply_failed
tool_start
tool_end
validation_start
validation_end
```

Every event contains:

```json
{
  "schema_version": "game-agent-jsonl-v2",
  "event": "model_end",
  "task_id": "8d12ab",
  "run_id": "8d12ab",
  "turn": 1,
  "round": 2,
  "component": "model",
  "ts": "2026-07-27T00:00:00Z"
}
```

Event-specific fields add duration, outcome, commands, outputs, actions, errors,
or Skill metadata. Start/end pairs use the same task, turn, and round values.

The current absence of a Skill runtime is represented by one `skill_not_found`
event with `reason="runtime_disabled"` per task. Future Skill implementations
must emit explicit search, match, application, and failure events.

## Task Artifacts

Each task owns:

```text
artifacts/console/{task_id}/
  config.json
  events.jsonl
  trajectory.json
  result.json
  diff.patch
```

- `config.json` is the resolved configuration snapshot.
- `events.jsonl` is the complete v2 append-only event stream.
- `trajectory.json` is the multi-turn linear Agent context and cumulative
  metadata, retaining the compatible trajectory structure where possible.
- `result.json` stores task status, last answer, cumulative statistics, and the
  last error.
- `diff.patch` captures tracked and untracked project modifications visible at
  finalization.

Artifacts are refreshed after every turn and during `/new`, `/exit`, normal EOF,
and interrupt handling. The console must not erase existing project changes.

## SSE Contract

The server emits one stable event type:

```text
id: 42
event: run_event
data: {"id":42,"event":"tool_end","created_at":"...","data":{...}}
```

The JSON envelope matches the history API item shape. This replaces arbitrary
SSE event types for the active internal client.

The React client:

1. Loads run details, history, and currently available resources.
2. Finds the largest history event ID.
3. Opens `/api/runs/{run_id}/events?after={largest_id}`.
4. Listens for `run_event`.
5. Parses, deduplicates, and orders events by ID.
6. Relies on native EventSource reconnect and `Last-Event-ID` recovery.
7. Refreshes run status when lifecycle events arrive.
8. On terminal state, fetches run, diff, trajectory, and artifacts, then closes
   the stream.
9. Uses a 15-second status reconciliation request only as a missed-terminal or
   backend-restart fallback.

The EventSource is closed on component unmount and when the run reaches a
terminal state.

## Error Handling

- Invalid console configuration or Unity project paths fail before creating a
  task.
- Model errors render under `[Model]`, update `result.json`, and return control
  to the prompt.
- Tool errors render under `[Env]` and remain observations available to the
  Agent unless the Environment raises a terminal exception.
- Limit exits render the exact limit type and completed round count.
- Artifact write errors are reported without hiding the original Agent result.
- Malformed SSE envelopes are ignored and reported in the page error state
  without discarding valid prior events.
- SSE transport errors show a reconnecting state; EventSource is allowed to
  reconnect automatically.

## Test Design

### Framework and Console Unit Tests

- First turn creates exactly one system and one initial user message.
- Follow-up turns retain previous assistant, action, and observation messages.
- Submission is converted into a continuation-safe assistant message.
- `/new` saves the old task and starts an empty context.
- Per-turn limits reset while task totals accumulate.
- Component events occur in this order:

```text
turn_start
agent_round_start
model_start
model_end or model_error
tool_start
tool_end
agent_observation_added
turn_end
```

- Every Model and tool start has exactly one end or error event.
- A disabled Skill runtime emits one explicit `skill_not_found`; command text
  containing "skill" does not produce Skill events.
- `/status`, `/diff`, `/help`, `/exit`, EOF, and interrupt behavior are covered.
- Tracked and untracked changes appear in `diff.patch`.
- Console output truncation does not truncate artifact data.

Tests use fixture models and temporary Unity project repositories and make no
external API calls.

### Backend Tests

- History and SSE return the same envelope shape.
- `after` and `Last-Event-ID` resume after the correct event.
- Terminal runs close the event stream after queued events are delivered.
- Final result, trajectory, diff, and artifacts remain available.

### Frontend Tests

The stream merge and lifecycle logic is extracted into a small module and tested
with a fake EventSource:

- history plus live events merge in ID order;
- duplicate IDs are ignored;
- malformed events do not erase valid state;
- lifecycle events request status refresh;
- terminal state triggers final resource refresh and stream closure;
- cleanup closes the active source.

The existing TypeScript check, production build, and Python test suite remain
required acceptance checks.

## Acceptance Criteria

- `game-agent-console` starts without FastAPI or React.
- A developer can complete multiple turns with inherited context and use `/new`
  for another independent task.
- The console makes every real Run-Agent-Model-Environment rotation observable.
- Skill output is truthful when the runtime is absent and ready for explicit
  future Skill events.
- Every turn reports the final answer and project modification summary.
- Task artifacts survive normal exit and interruption.
- The active React detail page receives new events through SSE without 2.5-second
  full-resource polling.
- Refresh and disconnect recovery do not lose or duplicate events.
- All automated tests, frontend type checking, and frontend production build
  pass.
