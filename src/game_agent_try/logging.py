from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class ExperimentLogger:
    """Append-only JSONL logger with a stable event schema."""

    EVENT_PHASES: dict[str, tuple[str, str]] = {
        "run_start": ("run", "start"),
        "run_end": ("run", "finish"),
        "task_start": ("run", "start"),
        "task_end": ("run", "finish"),
        "turn_start": ("run", "start"),
        "turn_end": ("run", "finish"),
        "agent_round_start": ("agent", "plan"),
        "agent_observation_added": ("agent", "observe"),
        "agent_progress_warning": ("agent", "observe"),
        "agent_limit_reached": ("agent", "finish"),
        "agent_finish": ("agent", "finish"),
        "model_preflight": ("model", "request"),
        "model_start": ("model", "request"),
        "model_usage": ("model", "response"),
        "model_end": ("model", "response"),
        "model_error": ("model", "error"),
        "tool_start": ("environment", "tool_start"),
        "tool_end": ("environment", "tool_end"),
        "validation_start": ("environment", "validate"),
        "validation_end": ("environment", "validate"),
        "skill_search_start": ("skill", "resolve"),
        "skill_matched": ("skill", "resolve"),
        "skill_not_found": ("skill", "resolve"),
        "skill_apply_start": ("skill", "apply"),
        "skill_apply_end": ("skill", "apply"),
        "skill_apply_failed": ("skill", "error"),
    }

    def __init__(
        self,
        path: Path,
        *,
        run_id: str,
        config_id: str,
        schema_version: str = "game-agent-jsonl-v3",
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
        self._started_ns = time.perf_counter_ns()

    def set_context(self, **context: Any) -> None:
        self.context.update(context)

    def emit(self, event: str, **data: Any) -> dict[str, Any]:
        self.sequence += 1
        monotonic_ns = time.perf_counter_ns()
        default_component, default_phase = self.EVENT_PHASES.get(event, ("run", "event"))
        component = data.pop("component", default_component)
        phase = data.pop("phase", default_phase)
        turn = data.pop("turn", self.context.get("turn", 0))
        round_number = data.pop("round", self.context.get("round", 0))
        record = {
            "schema_version": self.schema_version,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "monotonic_ns": monotonic_ns,
            "elapsed_ms": (monotonic_ns - self._started_ns) // 1_000_000,
            "run_id": self.run_id,
            "config_id": self.config_id,
            "seq": self.sequence,
            "event": event,
            **self.context,
            "component": component,
            "phase": phase,
            "turn": int(turn or 0),
            "round": int(round_number or 0),
            **data,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        for listener in self.listeners:
            listener(record)
        return record
