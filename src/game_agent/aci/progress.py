from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Iterable


class ProgressEventType(StrEnum):
    FRONTIER_IMPROVED = "frontier_improved"
    IMPLEMENTATION_READ = "implementation_read"
    DIAGNOSIS_ACCEPTED = "diagnosis_accepted"
    PATCH_PREPARED = "patch_prepared"
    MUTATION_APPLIED = "mutation_applied"
    MUTATION_FAILED = "mutation_failed"
    COMPILE_PASSED = "compile_passed"
    EDITMODE_PASSED = "editmode_passed"
    PLAYMODE_PASSED = "playmode_passed"
    VALIDATION_FAILED = "validation_failed"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    event_id: str
    event_type: ProgressEventType
    phase_before: str
    phase_after: str
    evidence_ids: list[str]
    details: dict[str, Any] = field(default_factory=dict)
    advances: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type.value
        return payload


class ProgressLedger:
    """Controller-owned semantic progress; tool-output novelty is deliberately irrelevant."""

    def __init__(self) -> None:
        self.version = 0
        self.events: list[ProgressEvent] = []

    def record(
        self,
        event_type: ProgressEventType,
        *,
        phase_before: str,
        phase_after: str,
        evidence_ids: Iterable[str],
        details: dict[str, Any] | None = None,
        advances: bool = True,
    ) -> ProgressEvent:
        ids = list(dict.fromkeys(str(value) for value in evidence_ids if value))
        if advances and not ids:
            raise ValueError(f"Semantic progress event {event_type.value} requires evidence")
        event = ProgressEvent(
            event_id=f"P{len(self.events) + 1}",
            event_type=event_type,
            phase_before=phase_before,
            phase_after=phase_after,
            evidence_ids=ids,
            details=dict(details or {}),
            advances=advances,
        )
        self.events.append(event)
        if advances:
            self.version += 1
        return event

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "events": [event.to_dict() for event in self.events],
        }
