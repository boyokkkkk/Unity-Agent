from __future__ import annotations

import json
import os
import subprocess
import tempfile
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from game_agent.mini import load_config, run
from game_agent.workspace import WorkspaceLease, create_task_workspace


def _write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


@dataclass(frozen=True)
class TaskBaseline:
    """Immutable Git tree representing the workspace when a task started."""

    project_path: str
    tree: str
    head: str | None
    status: tuple[str, ...]
    excluded_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _git(
    project_path: Path,
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=project_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _is_git_worktree(project_path: Path) -> bool:
    return _git(project_path, ["rev-parse", "--is-inside-work-tree"]).returncode == 0


def _project_exclusions(project_path: Path, paths: tuple[Path, ...]) -> tuple[str, ...]:
    excluded: list[str] = []
    for path in paths:
        try:
            relative = path.resolve().relative_to(project_path.resolve()).as_posix().strip("/")
        except ValueError:
            continue
        if relative and relative != ".":
            excluded.append(relative)
    return tuple(sorted(set(excluded)))


def _snapshot_tree(project_path: Path, excluded_paths: tuple[str, ...] = ()) -> str:
    """Write the current worktree to an isolated Git index and return its tree id."""
    with tempfile.TemporaryDirectory(prefix="game-agent-index-") as temporary:
        index_path = Path(temporary) / "index"
        env = dict(os.environ)
        env["GIT_INDEX_FILE"] = str(index_path)
        initialized = _git(project_path, ["read-tree", "HEAD"], env=env)
        if initialized.returncode != 0:
            initialized = _git(project_path, ["read-tree", "--empty"], env=env)
        if initialized.returncode != 0:
            raise RuntimeError(initialized.stderr.strip() or "Unable to initialize task baseline index")
        pathspecs = ["."] + [
            item
            for path in excluded_paths
            for item in (f":(exclude){path}", f":(exclude){path}/**")
        ]
        staged = _git(project_path, ["add", "-A", "--", *pathspecs], env=env)
        if staged.returncode != 0:
            raise RuntimeError(staged.stderr.strip() or "Unable to snapshot task workspace")
        tree = _git(project_path, ["write-tree"], env=env)
        if tree.returncode != 0:
            raise RuntimeError(tree.stderr.strip() or "Unable to write task baseline tree")
        return tree.stdout.strip()


def capture_task_baseline(
    project_path: Path,
    destination: Path | None = None,
    *,
    exclude_paths: tuple[Path, ...] = (),
) -> TaskBaseline | None:
    """Capture tracked and untracked workspace content without changing the user's index."""
    project_path = project_path.resolve()
    if not _is_git_worktree(project_path):
        return None
    excluded = _project_exclusions(project_path, exclude_paths)
    tree = _snapshot_tree(project_path, excluded)
    head_result = _git(project_path, ["rev-parse", "--verify", "HEAD"])
    status_result = _git(project_path, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    baseline = TaskBaseline(
        project_path=str(project_path),
        tree=tree,
        head=head_result.stdout.strip() if head_result.returncode == 0 else None,
        status=tuple(item for item in status_result.stdout.split("\0") if item),
        excluded_paths=excluded,
    )
    if destination is not None:
        _write_json(destination, baseline.to_dict())
    return baseline


def _capture_diff(
    project_path: Path,
    destination: Path,
    baseline: TaskBaseline | None = None,
) -> None:
    project_path = project_path.resolve()
    if not _is_git_worktree(project_path):
        destination.write_text("", encoding="utf-8")
        return
    if baseline is not None:
        current_tree = _snapshot_tree(project_path, baseline.excluded_paths)
        result = _git(
            project_path,
            ["diff", "--binary", "--no-ext-diff", baseline.tree, current_tree],
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Unable to capture task diff")
        destination.write_text(result.stdout, encoding="utf-8")
        return

    tracked = _git(project_path, ["diff", "--binary", "--no-ext-diff"])
    untracked = _git(project_path, ["ls-files", "--others", "--exclude-standard", "-z"])
    patches = [tracked.stdout]
    for name in filter(None, untracked.stdout.split("\0")):
        result = _git(project_path, ["diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", name])
        patches.append(result.stdout)
    destination.write_text("".join(patches), encoding="utf-8")


def prepare_run_config(source_path: Path, artifact_dir: Path, project_path: Path | None = None) -> Path:
    config = json.loads(json.dumps(load_config(source_path)))
    if project_path is not None:
        config["experiment"]["target_project"] = str(project_path)
        config["environment"]["cwd"] = str(project_path)
    config["logging"]["events_path"] = str(artifact_dir / "events.jsonl")
    config["logging"]["trajectory_path"] = str(artifact_dir / "trajectory.json")
    if "skills" in config:
        config["skills"]["paths"] = [
            str(path if path.is_absolute() else (source_path.parent / path).resolve())
            for raw_path in config["skills"].get("paths", [])
            for path in [Path(raw_path)]
        ]
    destination = artifact_dir / "config.json"
    _write_json(destination, config)
    return destination


def run_worker(run_id: str, task: str, config_path: str, project_path: str, artifact_dir: str) -> None:
    """Multiprocessing target. It communicates through files in its artifact directory."""
    artifacts = Path(artifact_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    baseline: TaskBaseline | None = None
    lease: WorkspaceLease | None = None
    working_project = Path(project_path).resolve()
    status = "failed"
    result: dict[str, Any] = {}
    try:
        source_config = load_config(Path(config_path))
        workspace_config = dict(source_config.get("workspace", {}))
        isolation_mode = str(workspace_config.get("isolation", "in_place"))
        configured_root = str(workspace_config.get("root", "")).strip()
        workspace_parent = (
            Path(configured_root).resolve()
            if configured_root
            else Path(tempfile.gettempdir()).resolve() / "game-agent-workspaces"
        )
        lease = create_task_workspace(working_project, workspace_parent / run_id, mode=isolation_mode)
        working_project = lease.project_path
        _write_json(
            artifacts / "workspace.json",
            {
                "source_project": str(lease.source_project),
                "project_path": str(working_project),
                "mode": lease.mode,
                "ephemeral": lease.mode != "in_place",
            },
        )
        baseline = capture_task_baseline(
            working_project,
            artifacts / "workspace-baseline.json",
            exclude_paths=(artifacts,),
        )
        resolved_config = prepare_run_config(Path(config_path), artifacts, working_project)
        result = run(task, resolved_config, run_id=run_id)
        status = "submitted" if result.get("exit_status") == "Submitted" else "failed"
    except BaseException as exc:
        result = {
            "exit_status": type(exc).__name__, "submission": "", "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        try:
            if lease is None:
                (artifacts / "diff.patch").write_text(
                    "Task diff unavailable: isolated workspace creation failed.\n",
                    encoding="utf-8",
                )
            elif baseline is None:
                (artifacts / "diff.patch").write_text(
                    "Task diff unavailable: workspace baseline capture failed.\n",
                    encoding="utf-8",
                )
            else:
                _capture_diff(working_project, artifacts / "diff.patch", baseline)
        except Exception as exc:
            (artifacts / "diff.patch").write_text(f"Diff capture failed: {exc}\n", encoding="utf-8")
        finally:
            if lease is not None:
                try:
                    lease.close()
                except Exception as exc:
                    result.setdefault("workspace_cleanup_error", str(exc))
                    result["exit_status"] = "WorkspaceCleanupError"
                    status = "failed"
        _write_json(artifacts / "result.json", {"run_id": run_id, "status": status, **result})
