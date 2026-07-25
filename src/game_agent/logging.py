from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class ExperimentLogger:
    """Append-only JSONL logger with a stable event schema."""

    def __init__(self, path: Path, *, run_id: str, config_id: str) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.config_id = config_id
        self.sequence = 0

    def emit(self, event: str, **data: Any) -> None:
        self.sequence += 1
        record = {
            "schema_version": "game-agent-jsonl-v1",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_id": self.run_id,
            "config_id": self.config_id,
            "seq": self.sequence,
            "event": event,
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
