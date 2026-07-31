from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .schemas import (
    ACI_TOOL_NAMES,
    ASSET_MUTATION_TOOL_NAMES,
    IMPLEMENTATION_READ_TOOL_NAMES,
    LOCALIZATION_TOOL_NAMES,
    SCRIPT_MUTATION_TOOL_NAMES,
    VALIDATION_TOOL_NAMES,
)


@dataclass(frozen=True, slots=True)
class ToolExposure:
    profile: str
    tool_names: tuple[str, ...]
    reason: str
    validation_locked: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def select_tool_exposure(
    *,
    phase: str,
    unresolved_slot_ids: Iterable[str],
    working_paths: Iterable[str],
    pending_stage: str = "",
    enabled: bool = True,
) -> ToolExposure:
    """Select the smallest safe ACI schema for the next model call."""
    if not enabled:
        return _exposure(
            "all",
            ACI_TOOL_NAMES,
            "Dynamic exposure is disabled by configuration.",
        )

    if pending_stage:
        return _exposure(
            "validation",
            VALIDATION_TOOL_NAMES,
            f"A checkpoint is pending at stage {pending_stage}; validation tools are locked visible.",
            validation_locked=True,
        )

    if phase in {"validation", "submission"}:
        return _exposure(
            "validation",
            VALIDATION_TOOL_NAMES,
            f"The context phase is {phase}.",
        )

    open_slots = set(unresolved_slot_ids)
    implementation_ready = not {
        "localized_target",
        "implementation_source",
    }.intersection(open_slots)
    if phase == "implementation" or implementation_ready:
        paths = [str(path).replace("\\", "/").casefold() for path in working_paths if path]
        mutation_names: set[str] = set()
        if any(path.endswith(".cs") for path in paths):
            mutation_names.update(SCRIPT_MUTATION_TOOL_NAMES)
        if any(path.endswith((".unity", ".prefab", ".asset")) for path in paths):
            mutation_names.update(ASSET_MUTATION_TOOL_NAMES)
        if not mutation_names:
            mutation_names.update(SCRIPT_MUTATION_TOOL_NAMES)
            mutation_names.update(ASSET_MUTATION_TOOL_NAMES)
        return _exposure(
            "implementation",
            IMPLEMENTATION_READ_TOOL_NAMES | mutation_names,
            "Localization and implementation-source evidence slots are resolved.",
        )

    return _exposure(
        "localization",
        LOCALIZATION_TOOL_NAMES,
        "Localization or implementation-source evidence is still unresolved.",
    )


def _exposure(
    profile: str,
    names: Iterable[str],
    reason: str,
    *,
    validation_locked: bool = False,
) -> ToolExposure:
    return ToolExposure(
        profile=profile,
        tool_names=tuple(sorted(set(names))),
        reason=reason,
        validation_locked=validation_locked,
    )
