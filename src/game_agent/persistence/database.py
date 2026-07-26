from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Thread-safe SQLite repository for local API runs."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.Lock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.session() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, task TEXT NOT NULL, status TEXT NOT NULL,
                    config_path TEXT NOT NULL, project_path TEXT NOT NULL, artifact_dir TEXT NOT NULL,
                    worker_pid INTEGER, exit_status TEXT NOT NULL DEFAULT '',
                    submission TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
                );
                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    source TEXT NOT NULL, source_seq INTEGER, event TEXT NOT NULL,
                    payload TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(run_id, source, source_seq)
                );
                CREATE INDEX IF NOT EXISTS idx_run_events_run_id_id ON run_events(run_id, id);
                CREATE TABLE IF NOT EXISTS artifacts (
                    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
                    name TEXT NOT NULL, path TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(run_id, name)
                );
            """)

    def create_run(self, data: dict[str, Any]) -> None:
        with self._write_lock, self.session() as connection:
            connection.execute("""INSERT INTO runs
                (run_id, task, status, config_path, project_path, artifact_dir, created_at)
                VALUES (:run_id, :task, :status, :config_path, :project_path, :artifact_dir, :created_at)""", data)

    def update_run(self, run_id: str, **changes: Any) -> None:
        if not changes:
            return
        allowed = {"status", "worker_pid", "exit_status", "submission", "error", "started_at", "finished_at"}
        invalid = set(changes) - allowed
        if invalid:
            raise ValueError(f"Unsupported run fields: {sorted(invalid)}")
        assignments = ", ".join(f"{key} = :{key}" for key in changes)
        with self._write_lock, self.session() as connection:
            connection.execute(f"UPDATE runs SET {assignments} WHERE run_id = :run_id", {"run_id": run_id, **changes})

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_event(self, run_id: str, event: str, payload: dict[str, Any], *,
                  source: str = "manager", source_seq: int | None = None) -> int | None:
        with self._write_lock, self.session() as connection:
            cursor = connection.execute("""INSERT OR IGNORE INTO run_events
                (run_id, source, source_seq, event, payload, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (run_id, source, source_seq, event, json.dumps(payload, ensure_ascii=False), utc_now()))
            return cursor.lastrowid if cursor.rowcount else None

    def list_events(self, run_id: str, *, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute("""SELECT id, event, payload, created_at FROM run_events
                WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?""", (run_id, after_id, limit)).fetchall()
        return [{"id": row["id"], "event": row["event"], "created_at": row["created_at"],
                 "data": json.loads(row["payload"])} for row in rows]

    def upsert_artifact(self, run_id: str, name: str, path: Path) -> None:
        with self._write_lock, self.session() as connection:
            connection.execute("""INSERT INTO artifacts (run_id, name, path, size, created_at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(run_id, name) DO UPDATE SET
                path=excluded.path, size=excluded.size""", (run_id, name, str(path), path.stat().st_size, utc_now()))

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as connection:
            rows = connection.execute(
                "SELECT name, path, size, created_at FROM artifacts WHERE run_id = ? ORDER BY name", (run_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_interrupted_runs(self) -> None:
        with self._write_lock, self.session() as connection:
            connection.execute("""UPDATE runs SET status='failed',
                error='API service restarted while worker was active', finished_at=?
                WHERE status IN ('pending', 'running')""", (utc_now(),))
