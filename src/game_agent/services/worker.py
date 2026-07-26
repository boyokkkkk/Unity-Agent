from __future__ import annotations

import json
import subprocess
import traceback
from pathlib import Path
from typing import Any

from game_agent.mini import load_config, run


def _write_json(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _capture_diff(project_path: Path, destination: Path) -> None:
    if not (project_path / ".git").exists():
        destination.write_text("", encoding="utf-8")
        return
    tracked = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=project_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=project_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    patches = [tracked.stdout]
    for name in filter(None, untracked.stdout.split("\0")):
        result = subprocess.run(
            ["git", "diff", "--no-index", "--binary", "--no-ext-diff", "--", "/dev/null", name],
            cwd=project_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        patches.append(result.stdout)
    destination.write_text("".join(patches), encoding="utf-8")


def prepare_run_config(source_path: Path, artifact_dir: Path, project_path: Path | None = None) -> Path:
    config = json.loads(json.dumps(load_config(source_path)))
    if project_path is not None:
        config["experiment"]["target_project"] = str(project_path)
        config["environment"]["cwd"] = str(project_path)
    config["logging"]["events_path"] = str(artifact_dir / "events.jsonl")
    config["logging"]["trajectory_path"] = str(artifact_dir / "trajectory.json")
    destination = artifact_dir / "config.json"
    _write_json(destination, config)
    return destination


def run_worker(run_id: str, task: str, config_path: str, project_path: str, artifact_dir: str) -> None:
    """Multiprocessing target. It communicates through files in its artifact directory."""
    artifacts = Path(artifact_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    status = "failed"
    result: dict[str, Any] = {}
    try:
        resolved_config = prepare_run_config(Path(config_path), artifacts, Path(project_path))
        result = run(task, resolved_config, run_id=run_id)
        status = "submitted" if result.get("exit_status") == "Submitted" else "failed"
    except BaseException as exc:
        result = {
            "exit_status": type(exc).__name__, "submission": "", "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        try:
            _capture_diff(Path(project_path), artifacts / "diff.patch")
        except Exception as exc:
            (artifacts / "diff.patch").write_text(f"Diff capture failed: {exc}\n", encoding="utf-8")
        _write_json(artifacts / "result.json", {"run_id": run_id, "status": status, **result})
