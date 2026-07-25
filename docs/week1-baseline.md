# Week 1 baseline decision

## Framework choice

Use a project-owned adapter inspired by mini-SWE-agent, not a direct dependency on its CLI for the experimental baseline.

mini-SWE-agent is useful for the model/environment/trajectory loop, but its default contract is a generic repository repair task. SkillGameAgent needs a narrower and stable contract: `read_file`, `write_file`, `compile`, `test`, and later Unity Editor validators. Keeping that contract in `src/game_agent` makes logs, task boundaries, and controlled variables reproducible. A mini-SWE-agent backend can be added behind the same interface after Week 1.

## Week 1 acceptance

- `configs/week1.json` fixes model placeholder, round/token limits, commands, task IDs, and log paths.
- `WorkspaceTools` restricts file access to the project root and emits JSONL tool events.
- Each task performs file read, one controlled edit, compile, and task-specific test.
- `baseline/Unity2D` is a standard Unity project layout. Its domain scripts also compile with `dotnet` when Unity Editor is unavailable.
- Unity PlayMode is never reported as passed without an Editor; the current environment records `skipped_unavailable`.
