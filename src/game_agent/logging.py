from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ExperimentLogger:
    """Append-only JSONL logger with a stable event schema."""

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        config_id: str,
        schema_version: str = "game-agent-jsonl-v1",
        context: dict[str, Any] | None = None,
        listeners: list[Callable[[dict[str, Any]], None]] | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.config_id = config_id
        self.schema_version = schema_version
        self.context = dict(context or {})
        self.listeners = list(listeners or [])
        self.sequence = 0

    def set_context(self, **context: Any) -> None:
        self.context.update(context)

    def emit(self, event: str, **data: Any) -> dict[str, Any]:
        self.sequence += 1
        record = {
            "schema_version": self.schema_version,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": self.run_id,
            "config_id": self.config_id,
            "seq": self.sequence,
            "event": event,
            **self.context,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        for listener in self.listeners:
            listener(record)
        return record
