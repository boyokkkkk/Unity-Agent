from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from .schemas import (
    ACI_TOOL_NAMES,
    ASSET_MUTATION_TOOL_NAMES,
    IMPLEMENTATION_READ_TOOL_NAMES,
    LOCALIZATION_TOOL_NAMES,
    MUTATION_TOOL_NAMES,
    SCRIPT_MUTATION_TOOL_NAMES,
    VALIDATION_TOOL_NAMES,
)
from .workflow import GLOBAL_SEARCH_TOOLS, GRAPH_EXPANSION_TOOLS, WorkflowPhase, WorkflowState


_VALIDATION_STAGE_TOOLS = {
    "static_diagnostics": frozenset({"code_diagnostics", "artifact_read"}),
    "recompile_or_hot_reload": frozenset({"unity_recompile"}),
    "runtime_validation": frozenset({"unity_validate", "artifact_read"}),
}


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
    workflow: WorkflowState | None = None,
) -> ToolExposure:
    """Select the smallest safe ACI schema for the next model call."""
    if not enabled:
        return _exposure(
            "all",
            ACI_TOOL_NAMES,
            "Dynamic exposure is disabled by configuration.",
        )

    if workflow is not None:
        return _workflow_exposure(workflow, working_paths, pending_stage=pending_stage)

    if pending_stage:
        names = _VALIDATION_STAGE_TOOLS.get(pending_stage, VALIDATION_TOOL_NAMES)
        return _exposure(
            "validation",
            names,
            f"A checkpoint is pending at stage {pending_stage}; only tools that can advance this stage are visible.",
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

        # Token optimization: Only expose essential mutation tools
        if any(path.endswith(".cs") for path in paths):
            mutation_names.add("unity_script_patch")
        if any(path.endswith((".unity", ".prefab", ".asset")) for path in paths):
            # Core asset tools only (3 instead of 9)
            mutation_names.update({
                "unity_serialized_property_set",
                "unity_component_add",
                "unity_asset_save",
            })
        if not mutation_names:
            # Default: script patch only (most common case)
            mutation_names.add("unity_script_patch")

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


def _workflow_exposure(
    workflow: WorkflowState,
    working_paths: Iterable[str],
    *,
    pending_stage: str = "",
) -> ToolExposure:
    """Dynamic tool exposure based on workflow phase."""
    phase = workflow.phase
    if phase == WorkflowPhase.PLAN:
        return _exposure(
            "plan",
            {"task_plan_submit"},
            "A structured plan is required before repository exploration.",
        )
    if pending_stage or phase == WorkflowPhase.VALIDATE:
        names = _VALIDATION_STAGE_TOOLS.get(pending_stage, VALIDATION_TOOL_NAMES)
        return _exposure(
            "validate",
            names,
            f"Workflow validation is locked at {pending_stage or phase.value}; only tools that can advance this stage are visible.",
            validation_locked=True,
        )
    if phase == WorkflowPhase.EXPLORE:
        return _exposure(
            "explore",
            GLOBAL_SEARCH_TOOLS | GRAPH_EXPANSION_TOOLS | {"artifact_read"},
            "Use the bounded search budget to form a candidate frontier.",
        )
    if phase == WorkflowPhase.INSPECT:
        recovery_active = bool(workflow.last_mutation_failure or workflow.stage_directive)
        recovery_tools = {"diagnosis_revise"} if recovery_active else set()
        return _exposure(
            "inspect",
            {
                "candidate_read", "code_file_read", "code_find_references",
                "unity_ref_search", "artifact_read",
            } | recovery_tools,
            (
                "A mutation failed; re-read the exact target or evidence and revise the diagnosis anchor."
                if recovery_active
                else "The frontier is locked; consume or expand a concrete candidate."
            ),
        )
    if phase == WorkflowPhase.DIAGNOSE:
        diagnosis_tool = (
            "diagnosis_revise" if workflow.diagnosis_history else "diagnosis_submit"
        )
        has_unread_candidate = any(
            candidate.read_level == "unread" for candidate in workflow.frontier.candidates()
        )
        diagnosis_reads = {"candidate_read"} if (
            workflow.missing_evidence_candidate_ids or has_unread_candidate
        ) else set()
        return _exposure(
            "diagnose",
            diagnosis_reads | {diagnosis_tool},
            (
                "Submit the evidence-linked diagnosis when causally supported, or inspect one unread candidate "
                "already present in the bounded frontier."
            ),
        )
    if phase == WorkflowPhase.EDIT:
        authorized_paths = [
            str(path).replace("\\", "/").casefold()
            for path in workflow.authorized_paths
            if path
        ]
        mutation_tools = (
            SCRIPT_MUTATION_TOOL_NAMES
            if authorized_paths and all(path.endswith(".cs") for path in authorized_paths)
            else MUTATION_TOOL_NAMES
        )
        return _exposure(
            "edit",
            mutation_tools | {"diagnosis_revise", "artifact_read", "code_file_read"},
            "Mutation targets and script patch text must exactly match the accepted diagnosis; target reads remain available for safe recovery.",
        )
    if phase == WorkflowPhase.REVIEW:
        return _exposure(
            "review",
            {"workflow_review"},
            "Run the controller-owned final review before submission is exposed.",
        )
    if phase == WorkflowPhase.SUBMIT:
        return _exposure("submit", {"submit"}, "Only final submission remains.")
    return _exposure("plan", set(), f"No executable tools are available during {phase.value}.")
