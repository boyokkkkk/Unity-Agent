# Unity Agent P0 trust contract

## Execution isolation

Managed workers read the optional `workspace` section:

```json
{
  "workspace": {
    "isolation": "auto",
    "root": ""
  }
}
```

`auto` creates a detached Git worktree when the project has a commit and overlays tracked dirty changes plus untracked files. Otherwise it creates a filtered copy and initializes an internal Git baseline. Unity-generated directories (`Library`, `Temp`, `Logs`, `obj`, `Build`, `Builds`, and `UserSettings`) are excluded. The source project is never mutated; the worker exports `diff.patch` and removes the ephemeral workspace after the run.

`in_place` remains available for legacy configurations, but does not provide task-level filesystem isolation.

## Unity validation

The optional `validation` section controls post-agent verification:

```json
{
  "validation": {
    "enabled": true,
    "editor_path": "",
    "modes": ["compile", "editmode", "playmode"],
    "timeout_seconds": 1200
  }
}
```

The editor is resolved from `editor_path`, `UNITY_EDITOR_PATH`, the Unity Hub path matching `ProjectVersion.txt`, or `PATH`. A missing editor produces `skipped_unavailable`, never `passed`. Results are written under `validation/` using schema `game-agent-unity-validation-v1`.

Validation fails when the Unity process returns non-zero, times out, omits/mangles its test XML, reports failed tests, or logs compiler errors. The preflight asset audit also fails on missing/orphan `.meta` files, duplicate GUIDs, or malformed Unity YAML. References whose GUID cannot be resolved inside `Assets` are warnings because they may belong to packages.

## Stable trajectory envelope

Trajectories use `schema_version: game-agent-trajectory-v1` while retaining upstream compatibility through `trajectory_format: mini-swe-agent-1.1`.

The stable required fields are:

- `schema_version` and `trajectory_format`;
- `info.framework_version`, `exit_status`, `submission`, `model_stats`, and `config`;
- `messages`, `turn_results`, and `applied_skills` arrays.

Component-specific fields are allowed. Every Agent save validates this envelope and atomically replaces the destination file, so readers never observe a partially written trajectory.

## Parity boundary

`tests/parity/` runs the local and vendored mini-SWE-agent 2.4.6 implementations with deterministic models and environments. It compares common message order, FormatError termination, cost/step boundaries, and common trajectory fields after normalizing local extensions. PowerShell, Unity guards, Skills, token limits, and progress guards are intentional local divergences and are tested separately.

