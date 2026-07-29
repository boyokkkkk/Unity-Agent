from __future__ import annotations

import json
import multiprocessing
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from game_agent.mini import load_config
from game_agent.persistence.database import Database, utc_now
from game_agent.processes import terminate_process_tree

from .worker import run_worker

TERMINAL_STATUSES = {"submitted", "failed", "cancelled", "timed_out"}


class RunManager:
    def __init__(self, database: Database, artifact_root: Path, *,
                 worker_target: Callable[..., None] = run_worker, poll_interval: float = 0.2) -> None:
        self.database = database
        self.artifact_root = artifact_root.resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.worker_target = worker_target
        self.poll_interval = poll_interval
        self._processes: dict[str, multiprocessing.Process] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._cancelling: set[str] = set()
        self._lock = threading.RLock()
        self.database.mark_interrupted_runs()

    def create(self, *, task: str, config_path: Path, project_path: Path | None = None) -> dict[str, Any]:
        config_path = config_path.resolve()
        config = load_config(config_path)
        resolved_project = (project_path or Path(config["environment"]["cwd"])).resolve()
        if not resolved_project.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {resolved_project}")
        if not (resolved_project / "ProjectSettings" / "ProjectVersion.txt").is_file():
            raise ValueError(f"Not a Unity project: {resolved_project}")
        self._assert_workspace_available(resolved_project)

        run_id = uuid.uuid4().hex[:12]
        artifact_dir = self.artifact_root / run_id
        artifact_dir.mkdir(parents=True, exist_ok=False)
        try:
            self.database.create_run({
                "run_id": run_id, "task": task, "status": "pending", "config_path": str(config_path),
                "project_path": str(resolved_project), "artifact_dir": str(artifact_dir), "created_at": utc_now(),
            })
        except sqlite3.IntegrityError as exc:
            artifact_dir.rmdir()
            if "runs.project_path" in str(exc):
                raise RuntimeError(f"Unity workspace is already in use: {resolved_project}") from exc
            raise
        self.database.add_event(run_id, "run_created", {"run_id": run_id, "status": "pending"})
        process = multiprocessing.Process(
            target=self.worker_target,
            args=(run_id, task, str(config_path), str(resolved_project), str(artifact_dir)),
            name=f"game-agent-{run_id}",
        )
        try:
            process.start()
        except Exception as exc:
            self.database.update_run(
                run_id, status="failed", exit_status="WorkerStartError",
                error=str(exc), finished_at=utc_now(),
            )
            self.database.add_event(run_id, "worker_start_failed", {"run_id": run_id, "error": str(exc)})
            raise RuntimeError(f"Could not start worker: {exc}") from exc
        with self._lock:
            self._processes[run_id] = process
        self.database.update_run(run_id, status="running", worker_pid=process.pid, started_at=utc_now())
        self.database.add_event(run_id, "worker_started", {
            "run_id": run_id, "status": "running", "worker_pid": process.pid,
        })
        monitor = threading.Thread(target=self._monitor, args=(run_id,), daemon=True, name=f"monitor-{run_id}")
        with self._lock:
            self._threads[run_id] = monitor
        monitor.start()
        return self.get(run_id)

    def _assert_workspace_available(self, project_path: Path) -> None:
        for item in self.database.list_runs(limit=1000):
            if item["status"] in {"pending", "running"} and Path(item["project_path"]) == project_path:
                raise RuntimeError(f"Unity workspace is already in use by run {item['run_id']}")

    def _monitor(self, run_id: str) -> None:
        offset = 0
        process = self._processes[run_id]
        events_path = Path(self.get(run_id)["artifact_dir"]) / "events.jsonl"
        while process.is_alive():
            offset = self._ingest_events(run_id, events_path, offset)
            time.sleep(self.poll_interval)
        process.join()
        self._ingest_events(run_id, events_path, offset)
        current = self.database.get_run(run_id)
        with self._lock:
            cancelling = run_id in self._cancelling
        if current and current["status"] not in {"cancelled", "timed_out"} and not cancelling:
            self._finish_from_result(run_id, process.exitcode)
        self._index_artifacts(run_id)
        with self._lock:
            self._processes.pop(run_id, None)
            self._threads.pop(run_id, None)

    def _ingest_events(self, run_id: str, path: Path, offset: int) -> int:
        if not path.exists():
            return offset
        with path.open("r", encoding="utf-8") as handle:
            handle.seek(offset)
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith("\n"):
                        handle.seek(line_start)
                        break
                    continue
                self.database.add_event(run_id, payload.get("event", "agent_event"), payload,
                                        source="worker", source_seq=payload.get("seq"))
            return handle.tell()

    def _finish_from_result(self, run_id: str, exitcode: int | None) -> None:
        run_data = self.get(run_id)
        result_path = Path(run_data["artifact_dir"]) / "result.json"
        if result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
            status = result.get("status", "failed")
            error = result.get("error", "")
            exit_status = result.get("exit_status", "")
            submission = result.get("submission", "")
        else:
            status, exit_status, submission = "failed", "WorkerProcessError", ""
            error = f"Worker exited with code {exitcode} without result.json"
        self.database.update_run(run_id, status=status, exit_status=exit_status, submission=submission,
                                 error=error, finished_at=utc_now())
        self.database.add_event(run_id, "run_status_changed", {
            "run_id": run_id, "status": status, "exit_status": exit_status, "error": error,
        })

    def cancel(self, run_id: str) -> dict[str, Any]:
        run_data = self.get(run_id)
        if run_data["status"] in TERMINAL_STATUSES:
            return run_data
        with self._lock:
            process = self._processes.get(run_id)
            self._cancelling.add(run_id)
        try:
            if process and process.is_alive():
                self._terminate_process_tree(process)
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=5)
            self.database.update_run(
                run_id, status="cancelled", exit_status="Cancelled", finished_at=utc_now()
            )
            self.database.add_event(run_id, "run_cancelled", {"run_id": run_id, "status": "cancelled"})
            return self.get(run_id)
        finally:
            with self._lock:
                self._cancelling.discard(run_id)

    @staticmethod
    def _terminate_process_tree(process: multiprocessing.Process) -> None:
        if process.pid:
            terminate_process_tree(process.pid)

    def _index_artifacts(self, run_id: str) -> None:
        root = Path(self.get(run_id)["artifact_dir"])
        for path in root.rglob("*"):
            if path.is_file():
                self.database.upsert_artifact(run_id, path.relative_to(root).as_posix(), path)

    def get(self, run_id: str) -> dict[str, Any]:
        run_data = self.database.get_run(run_id)
        if run_data is None:
            raise KeyError(run_id)
        return run_data

    def list(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        return self.database.list_runs(limit=limit, offset=offset)

    def events(self, run_id: str, *, after_id: int = 0) -> list[dict[str, Any]]:
        self.get(run_id)
        return self.database.list_events(run_id, after_id=after_id)

    def artifacts(self, run_id: str) -> list[dict[str, Any]]:
        self.get(run_id)
        self._index_artifacts(run_id)
        return self.database.list_artifacts(run_id)

    def artifact_path(self, run_id: str, name: str) -> Path:
        root = Path(self.get(run_id)["artifact_dir"]).resolve()
        candidate = (root / name).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Artifact path escapes run directory")
        if not candidate.is_file():
            raise FileNotFoundError(name)
        return candidate

    def shutdown(self) -> None:
        with self._lock:
            run_ids = list(self._processes)
            monitors = list(self._threads.values())
        for run_id in run_ids:
            self.cancel(run_id)
        current = threading.current_thread()
        for monitor in monitors:
            if monitor is not current:
                monitor.join(timeout=5)
