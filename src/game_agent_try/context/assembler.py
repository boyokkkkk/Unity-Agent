from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import (
    ContextMemory,
    EvidenceLedger,
    EvidenceStatus,
    TaskWorkingSet,
    ToolObservation,
)
from .project_store import ProjectContextStore


PATH_PATTERN = re.compile(
    r"(?P<path>(?:Assets|Packages)[\\/][^\s\"'`,;:\]\}\<\>\(\)]+)",
    re.IGNORECASE,
)
RANGE_PATTERN = re.compile(
    r"(?P<path>(?:Assets|Packages)[\\/][^\s:\"']+)[\(:](?P<line>\d+)(?:[,\):](?P<column>\d+))?",
    re.IGNORECASE,
)
DEFAULT_PHASE_PLAN = (
    ("task_understanding", "Parse the task and constraints."),
    ("scope_localization", "Map the bounded project working set."),
    ("evidence_verification", "Verify candidates and root-cause evidence."),
    ("diagnosis", "Resolve remaining hypotheses and failures."),
    ("implementation", "Apply the smallest planned change."),
    ("validation", "Compile, test, and review the impact."),
    ("submission", "Submit an evidence-backed result."),
)


class ContextConfig(BaseModel):
    """Configuration for project-backed model-context virtualization."""

    enabled: bool = True
    graph_path: str = ""
    state_path: str = ""
    auto_locate: bool = True
    retrieval_strategy: Literal[
        "relevance", "path_collapse", "path_quota", "role_mmr"
    ] = "role_mmr"
    max_test_candidates: int = Field(default=1, ge=0)
    retrieval_mmr_lambda: float = Field(default=0.82, ge=0.0, le=1.0)
    max_working_set_entries: int = Field(default=24, ge=1)
    max_candidate_details: int = Field(default=5, ge=0)
    max_recent_tool_results: int = Field(default=1, ge=0)
    max_recent_messages: int = Field(default=4, ge=0)
    detail_char_limit: int = Field(default=1600, ge=128)
    tool_summary_char_limit: int = Field(default=900, ge=128)
    compression_trigger_ratio: float = Field(default=0.65, gt=0.0, le=1.0)
    working_set_detail_keep: int = Field(default=5, ge=0)
    max_evidence_items: int = Field(default=20, ge=1)
    max_memory_items_per_field: int = Field(default=20, ge=1)
    max_durable_instruction_chars: int = Field(default=10000, ge=512)


class ContextAssembler:
    """Build a bounded per-call view while retaining full history for audit."""

    def __init__(
        self,
        config: ContextConfig | dict[str, Any] | None = None,
        *,
        project_root: Path | None = None,
        artifact_root: Path | None = None,
        project_store: ProjectContextStore | None = None,
        event_sink: Callable[..., object] | None = None,
    ) -> None:
        self.config = config if isinstance(config, ContextConfig) else ContextConfig(**(config or {}))
        self.project_root = (project_root or Path.cwd()).resolve()
        self.artifact_root = artifact_root.resolve() if artifact_root else None
        self.event_sink = event_sink
        self.project_store = project_store or self._open_store()
        self.task_id = ""
        self.original_task = ""
        self.turn_requests: list[str] = []
        self.phase = "task_understanding"
        self.phase_goal = "Understand the request and establish a bounded project working set."
        self.plan: list[dict[str, str]] = self._default_plan()
        self.memory = ContextMemory()
        self.evidence = EvidenceLedger()
        self.recent_tools: list[ToolObservation] = []
        self.previous_phase = self.phase
        self.compression_count = 0
        self.build_count = 0
        self.raw_input_tokens = 0
        self.assembled_input_tokens = 0
        self.tokens_avoided = 0
        self.last_compression_reasons: list[str] = []
        self.structured_query_count = 0
        self.structured_query_nodes_mapped = 0
        self.structured_query_evidence_count = 0
        self.control_state: dict[str, Any] = {}

    @property
    def working_set(self) -> TaskWorkingSet:
        if self.project_store is not None:
            return self.project_store.working_set(
                self.task_id or "unbound",
                max_entries=self.config.max_working_set_entries,
            )
        if not hasattr(self, "_standalone_working_set"):
            self._standalone_working_set = TaskWorkingSet(
                self.task_id or "unbound",
                max_entries=self.config.max_working_set_entries,
            )
        return self._standalone_working_set

    def reset(self, task: str, *, task_id: str = "") -> None:
        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.original_task = task
        self.turn_requests = [task]
        self.phase = "task_understanding"
        self.previous_phase = self.phase
        self.phase_goal = "Understand the request and establish a bounded project working set."
        self.plan = self._default_plan()
        self.memory = ContextMemory()
        self.evidence = EvidenceLedger()
        self.recent_tools = []
        self.compression_count = 0
        self.build_count = 0
        self.raw_input_tokens = 0
        self.assembled_input_tokens = 0
        self.tokens_avoided = 0
        self.last_compression_reasons = []
        self.structured_query_count = 0
        self.structured_query_nodes_mapped = 0
        self.structured_query_evidence_count = 0
        self.control_state = {}
        if hasattr(self, "_standalone_working_set"):
            del self._standalone_working_set
        if self.project_store is not None:
            self.project_store.working_sets.pop(self.task_id, None)
            if self.config.auto_locate:
                try:
                    entries = self.project_store.locate(
                        self.task_id,
                        task,
                        limit=self.config.max_working_set_entries,
                        strategy=self.config.retrieval_strategy,
                        max_test_candidates=self.config.max_test_candidates,
                        mmr_lambda=self.config.retrieval_mmr_lambda,
                    )
                except (OSError, ValueError):
                    entries = []
                if entries:
                    self._set_phase(
                        "scope_localization",
                        "Map the smallest relevant code and Unity asset working set before broad exploration.",
                    )
                    for entry in entries:
                        evidence = self.evidence.add(
                            f"Project graph recommends {entry.kind} {entry.name} ({entry.path or entry.node_id}).",
                            status=EvidenceStatus.SUGGESTED,
                            sources=[f"graph:{entry.node_id}"],
                            node_ids=[entry.node_id],
                            confidence=min(1.0, max(0.0, entry.relevance)),
                            repository_revision=self._project_revision(),
                        )
                        entry.evidence_ids.append(evidence.id)
                        # Auto-label working set entries with evidence as relevant
                        self.working_set.label(entry.node_id, True, evidence_id=evidence.id)

    def begin_turn(self, task: str) -> None:
        if not self.task_id:
            self.reset(task)
            return
        self.turn_requests.append(task)
        self.memory.add_unique("unresolved_questions", task)

    def update_plan(self, steps: list[dict[str, str]]) -> None:
        self.plan = [
            {"step": str(item.get("step", "")), "status": str(item.get("status", "pending"))}
            for item in steps
            if item.get("step")
        ]

    def record_decision(self, decision: str) -> None:
        self.memory.add_unique("decisions", decision)

    def record_verified_fact(
        self,
        claim: str,
        *,
        sources: list[str],
        node_ids: list[str] | None = None,
        runtime_verified: bool = False,
        confidence: float = 1.0,
    ) -> str:
        status = EvidenceStatus.RUNTIME_VERIFIED if runtime_verified else EvidenceStatus.SOURCE_VERIFIED
        evidence = self.evidence.add(
            claim,
            status=status,
            sources=sources,
            node_ids=node_ids or [],
            confidence=confidence,
            repository_revision=self._project_revision(),
        )
        self.memory.add_unique("verified_facts", claim)
        for node_id in node_ids or []:
            self.working_set.label(node_id, True, evidence_id=evidence.id)
        return evidence.id

    def reject_hypothesis(
        self,
        hypothesis: str,
        *,
        sources: list[str] | None = None,
        node_ids: list[str] | None = None,
    ) -> str:
        evidence = self.evidence.add(
            hypothesis,
            status=EvidenceStatus.REJECTED,
            sources=sources or [],
            node_ids=node_ids or [],
            confidence=1.0,
            repository_revision=self._project_revision(),
        )
        self.memory.add_unique("rejected_hypotheses", hypothesis)
        for node_id in node_ids or []:
            self.working_set.label(node_id, False, evidence_id=evidence.id)
        return evidence.id

    def record_unresolved_question(self, question: str) -> None:
        self.memory.add_unique("unresolved_questions", question)

    def set_control_state(self, state: dict[str, Any]) -> None:
        self.control_state = dict(state)

    def assemble(
        self,
        messages: list[dict],
        *,
        raw_input_tokens: int = 0,
        max_input_tokens: int = 0,
        budget: dict[str, Any] | None = None,
    ) -> list[dict]:
        if not self.config.enabled or not messages:
            return list(messages)
        self.build_count += 1
        self.raw_input_tokens = raw_input_tokens
        compression_reasons: list[str] = []
        if self.project_store is not None:
            changed = self.project_store.detect_changes()
            for path in changed:
                self.memory.add_unique("changed_files", path)
            if changed:
                compression_reasons.append("project_graph_invalidation")

        ratio = raw_input_tokens / max_input_tokens if max_input_tokens > 0 else 0.0
        if ratio >= self.config.compression_trigger_ratio:
            compression_reasons.append("token_threshold")
        if self.previous_phase != self.phase:
            compression_reasons.append("phase_transition")
        if len(self.recent_tools) > self.config.max_recent_tool_results:
            compression_reasons.append("old_tool_results_externalized")
        if compression_reasons:
            self._compress(compression_reasons)
        self.previous_phase = self.phase

        details = self._candidate_details()
        system = self._stable_system_message(messages)
        durable_instructions = self._durable_instructions(messages)
        view = self._render_view(
            details=details,
            budget=budget or {},
            durable_instructions=durable_instructions,
            recent_messages=self._recent_messages(messages, durable_instructions),
        )
        self._emit(
            "context_assembled",
            raw_message_count=len(messages),
            assembled_message_count=2,
            raw_input_tokens=raw_input_tokens,
            phase=self.phase,
            compression_reasons=compression_reasons,
            working_set_metrics=self.working_set.metrics(),
        )
        return [system, {"role": "user", "content": view, "extra": {"virtual_context": True}}]

    def record_context_size(self, *, raw_tokens: int, assembled_tokens: int) -> None:
        self.raw_input_tokens = raw_tokens
        self.assembled_input_tokens = assembled_tokens
        self.tokens_avoided += max(0, raw_tokens - assembled_tokens)

    def record_tool_transition(
        self,
        actions: list[dict],
        outputs: list[dict],
        observations: list[dict],
    ) -> None:
        for index, action in enumerate(actions):
            output = outputs[index] if index < len(outputs) else {}
            observation = observations[index] if index < len(observations) else {}
            tool_name = str(action.get("tool", ""))
            command = str(action.get("command", "")) or tool_name
            content = _message_text(observation) or str(output.get("output", ""))
            extra = dict(output.get("extra", {})) | dict(observation.get("extra", {}))
            category = (
                "mutation" if extra.get("aci_mutation")
                else "validation" if extra.get("aci_control")
                else "workflow" if extra.get("aci_workflow")
                else "query" if extra.get("aci")
                else _command_category(command)
            )
            success = int(output.get("returncode", -1)) == 0
            if action.get("tool") == "submit" and success:
                self._set_phase("submission", "Submit the bounded result with evidence and limitations.")
            artifact_ref = str(extra.get("artifact_path", ""))
            if artifact_ref:
                self.memory.add_unique("artifact_references", artifact_ref)
            tool_observation = ToolObservation(
                summary=_summarize_tool_result(
                    content,
                    exception_info=str(output.get("exception_info", "")),
                    limit=self.config.tool_summary_char_limit,
                ),
                artifact_ref=artifact_ref,
                important_ranges=_important_ranges(content),
                truncated=bool(extra.get("output_truncated", False)),
                command=command,
                category=category,
                success=success,
            )

            # Token optimization: Don't add successful validation to recent_tools (saves ~800 tokens)
            skip_recent_tools = category == "validation" and success
            if not skip_recent_tools:
                self.recent_tools.append(tool_observation)

            if extra.get("aci"):
                self._record_structured_query(tool_name, extra)
                if category == "query":
                    self._set_phase(
                        "evidence_verification",
                        "Verify structured project-graph candidates and retain their evidence.",
                    )
                structured = extra.get("structured", {})
                diagnostic_errors = any(
                    str(item.get("severity", "")).casefold() == "error"
                    for item in structured.get("diagnostics", [])
                    if isinstance(item, dict)
                ) if isinstance(structured, dict) else False
                if (
                    tool_name == "code_diagnostics"
                    and success
                    and isinstance(structured, dict)
                    and structured.get("status") != "unavailable"
                    and not diagnostic_errors
                ):
                    if "static_diagnostics" in self.memory.pending_validations:
                        self.memory.pending_validations.remove("static_diagnostics")
            if category == "mutation" and success:
                changed_paths = [
                    str(value) for value in extra.get("changed_paths", []) if value
                ]
                for path in changed_paths:
                    self.memory.add_unique("changed_files", path)
                if self.project_store is not None:
                    self.project_store.invalidate_paths(changed_paths, reason="typed_aci_mutation")
                self.memory.add_unique("pending_validations", "static_diagnostics")
                if tool_name in {"unity_script_patch", "unity_execute_csharp"}:
                    self.memory.add_unique("pending_validations", "compile")
                self._set_phase(
                    "implementation",
                    "Verify the checkpointed typed Unity mutation through the controller protocol.",
                )
            paths = _extract_paths(command + "\n" + content)
            if category in {"read", "search"}:
                self._record_inspected_paths(paths)
                self._set_phase(
                    "evidence_verification",
                    "Verify graph candidates against the smallest necessary source and asset details.",
                )
            elif category == "write":
                for path in paths:
                    self.memory.add_unique("changed_files", path)
                if self.project_store is not None:
                    self.project_store.invalidate_paths(paths, reason="agent_write")
                self.memory.add_unique("pending_validations", "compile")
                self._set_phase("implementation", "Apply the planned minimal change and track its impact.")
            elif category == "validation":
                modes = [str(value) for value in extra.get("validation_modes", []) if value]
                for mode in modes or [command]:
                    self._record_validation(mode, success, tool_observation)
            if not success:
                self.memory.last_failure = {
                    "category": category,
                    "summary": tool_observation.summary,
                    "artifact_ref": artifact_ref,
                    "timestamp": tool_observation.timestamp,
                }
        self._emit(
            "context_tool_results_externalized",
            tool_results=len(actions),
            artifact_refs=[item.artifact_ref for item in self.recent_tools[-len(actions):] if item.artifact_ref],
        )

    def _record_structured_query(self, tool_name: str, extra: dict[str, Any]) -> None:
        self.structured_query_count += 1
        claim = str(extra.get("evidence_claim", "")).strip()
        if not claim:
            return
        raw_status = str(extra.get("evidence_status", "observed"))
        try:
            status = EvidenceStatus(raw_status)
        except ValueError:
            status = EvidenceStatus.OBSERVED
        node_ids = [str(value) for value in extra.get("node_ids", []) if value]
        sources = [str(value) for value in extra.get("evidence_sources", []) if value]
        artifact_path = str(extra.get("evidence_artifact_path", "")).strip() or None
        artifact_sha256 = str(extra.get("evidence_artifact_sha256", "")).strip() or None
        evidence = self.evidence.add(
            claim,
            status=status,
            sources=sources or [f"aci:{tool_name}"],
            node_ids=node_ids,
            confidence=0.9 if status == EvidenceStatus.SOURCE_VERIFIED else 0.65,
            repository_revision=self._project_revision(),
            artifact_path=artifact_path,
            artifact_sha256=artifact_sha256,
        )
        self.structured_query_evidence_count += 1
        self.structured_query_nodes_mapped += len(set(node_ids))
        if self.project_store is not None:
            self.project_store.map_node_ids(self.task_id or "unbound", node_ids)
        for node_id in node_ids:
            entry = self.working_set.entries.get(node_id)
            if entry is not None and evidence.id not in entry.evidence_ids:
                entry.evidence_ids.append(evidence.id)
                # Auto-label as relevant when evidence is added
                if entry.relevance_label is None:
                    entry.relevance_label = True
        if status in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}:
            self.memory.add_unique("verified_facts", claim)

    def serialize(self) -> dict[str, Any]:
        if self.project_store is not None:
            self.project_store.save_state()
        return {
            "enabled": self.config.enabled,
            "task_id": self.task_id,
            "original_task": self.original_task,
            "phase": self.phase,
            "phase_goal": self.phase_goal,
            "plan": self.plan,
            "memory": self.memory.to_dict(),
            "evidence_ledger": self.evidence.to_dict(),
            "working_set": self.working_set.to_dict(),
            "project_context": self.project_store.to_dict() if self.project_store else None,
            "metrics": self.metrics(),
        }

    def metrics(self) -> dict[str, Any]:
        return {
            **self.working_set.metrics(),
            "context_builds": self.build_count,
            "compression_count": self.compression_count,
            "raw_input_tokens_last": self.raw_input_tokens,
            "assembled_input_tokens_last": self.assembled_input_tokens,
            "tokens_avoided_estimate": self.tokens_avoided,
            "last_compression_reasons": self.last_compression_reasons,
            "structured_query_calls": self.structured_query_count,
            "structured_query_nodes_mapped": self.structured_query_nodes_mapped,
            "structured_query_evidence": self.structured_query_evidence_count,
            "control_state": self.control_state,
        }

    def _open_store(self) -> ProjectContextStore | None:
        if not self.config.graph_path:
            return None
        graph_path = Path(self.config.graph_path)
        if not graph_path.is_absolute():
            graph_path = (self.project_root / graph_path).resolve()
        if not graph_path.is_file():
            raise FileNotFoundError(f"Configured project graph does not exist: {graph_path}")
        if self.config.state_path:
            state_path = Path(self.config.state_path)
            if not state_path.is_absolute():
                state_path = (self.artifact_root or self.project_root) / state_path
        elif self.artifact_root:
            state_path = self.artifact_root / "project-context-state.json"
        else:
            state_path = None
        return ProjectContextStore.open(
            graph_path,
            project_root=self.project_root,
            state_path=state_path,
        )

    def _candidate_details(self) -> list[dict[str, Any]]:
        candidates = sorted(
            self.working_set.entries.values(),
            key=lambda entry: (
                entry.status == "verified",
                bool(entry.evidence_ids),
                entry.relevance,
                entry.last_accessed_at,
            ),
            reverse=True,
        )
        details: list[dict[str, Any]] = []
        for entry in candidates[: self.config.max_candidate_details]:
            if self.project_store is not None:
                detail = self.project_store.materialize(self.task_id, entry.node_id)
            else:
                hit = entry.detail is not None
                self.working_set.record_access(entry.node_id, hit=hit)
                detail = entry.detail
            if detail is None:
                detail = {
                    "id": entry.node_id,
                    "kind": entry.kind,
                    "name": entry.name,
                    "path": entry.path,
                    "status": entry.status,
                    "stale_reason": entry.stale_reason,
                }
            details.append(_bounded_json(detail, self.config.detail_char_limit))
        return details

    def _compress(self, reasons: list[str]) -> None:
        self.compression_count += 1
        self.last_compression_reasons = list(dict.fromkeys(reasons))
        self.working_set.evict_details(keep=self.config.working_set_detail_keep)
        if len(self.recent_tools) > self.config.max_recent_tool_results:
            removed = self.recent_tools[: -self.config.max_recent_tool_results or None]
            self.recent_tools = self.recent_tools[-self.config.max_recent_tool_results :] if self.config.max_recent_tool_results else []
            if removed:
                self.memory.conversation_summary = (
                    f"Externalized {len(removed)} older tool result(s); durable facts, failures, "
                    "changed files, and artifact references remain in structured memory."
                )
        self._emit("context_compressed", reasons=self.last_compression_reasons, metrics=self.metrics())

    def _record_inspected_paths(self, paths: list[str]) -> None:
        if self.project_store is not None:
            mapped = self.project_store.map_paths(self.task_id, paths)
        else:
            mapped = []
        for path in paths:
            node_ids = [entry.node_id for entry in mapped if _same_path(entry.path, path)]
            evidence = self.evidence.add(
                f"Source or asset was inspected: {path}.",
                status=EvidenceStatus.OBSERVED,
                sources=[path],
                node_ids=node_ids,
                confidence=0.5,
                repository_revision=self._project_revision(),
            )
            for node_id in node_ids:
                if node_id in self.working_set.entries:
                    entry = self.working_set.entries[node_id]
                    if evidence.id not in entry.evidence_ids:
                        entry.evidence_ids.append(evidence.id)

    def _record_validation(self, command: str, success: bool, observation: ToolObservation) -> None:
        lowered = command.casefold()
        validation = "playmode" if "playmode" in lowered else "editmode" if "editmode" in lowered else "compile"
        if success:
            # Token optimization: Success = minimal indicator, don't keep verbose summary
            if validation in self.memory.pending_validations:
                self.memory.pending_validations.remove(validation)
            self.memory.last_failure = None
            evidence = self.evidence.add(
                f"{validation} validation passed.",
                status=EvidenceStatus.RUNTIME_VERIFIED,
                sources=[observation.artifact_ref or f"command:{command}"],
                confidence=1.0,
                repository_revision=self._project_revision(),
            )
            self.memory.add_unique("verified_facts", evidence.claim)
            self._set_phase("validation", "Complete remaining validation and review evidence before submission.")
            # Don't append to recent_tools for successful validations - saves ~800 tokens per validation
        else:
            # Failure: Keep detailed summary in recent_tools for diagnosis
            self.memory.add_unique("pending_validations", validation)
            self._set_phase("diagnosis", "Use the latest structured validation failure to revise the root-cause hypothesis.")
            # observation is already in recent_tools from the caller

    def _set_phase(self, phase: str, goal: str) -> None:
        if phase != self.phase:
            self.previous_phase = self.phase
        self.phase = phase
        self.phase_goal = goal
        phase_indexes = {
            item.get("phase"): index
            for index, item in enumerate(self.plan)
            if item.get("phase")
        }
        if phase in phase_indexes:
            current = phase_indexes[phase]
            for index, item in enumerate(self.plan):
                item["status"] = "completed" if index < current else "in_progress" if index == current else "pending"

    def _project_revision(self) -> str:
        return self.project_store.version.project_revision if self.project_store is not None else ""

    @staticmethod
    def _default_plan() -> list[dict[str, str]]:
        return [
            {
                "phase": phase,
                "step": step,
                "status": "in_progress" if index == 0 else "pending",
            }
            for index, (phase, step) in enumerate(DEFAULT_PHASE_PLAN)
        ]

    def _render_view(
        self,
        *,
        details: list[dict[str, Any]],
        budget: dict[str, Any],
        durable_instructions: list[str],
        recent_messages: list[dict[str, str]],
    ) -> str:
        verified = [item.to_context_dict() for item in self.evidence.verified()][-self.config.max_evidence_items :]
        active = [
            item.to_context_dict() for item in self.evidence.active()
            if item.status != EvidenceStatus.SUGGESTED
        ][-self.config.max_evidence_items :]
        suggested = [
            item.to_context_dict() for item in self.evidence.active()
            if item.status == EvidenceStatus.SUGGESTED
        ][: self.config.max_evidence_items]
        working_refs = [
            {
                "id": entry.node_id,
                "kind": entry.kind,
                "name": entry.name,
                "path": entry.path,
                "status": entry.status,
                "evidence_ids": entry.evidence_ids,
            }
            for entry in self.working_set.entries.values()
        ]
        recent_tools = [item.to_dict() for item in self.recent_tools[-self.config.max_recent_tool_results :]]
        workflow = self.control_state.get("workflow", {})
        compact_control = {
            key: value for key, value in self.control_state.items()
            if key != "workflow"
        }
        context_metrics = self.metrics()
        context_metrics.pop("control_state", None)
        payload = {
            "task": self.original_task,
            "latest_request": self.turn_requests[-1] if self.turn_requests else self.original_task,
            "durable_task_instructions": durable_instructions,
            "phase": {"name": self.phase, "goal": self.phase_goal},
            "plan": self.plan,
            "context_memory": self._bounded_memory(),
            "verified_evidence": verified,
            "observed_evidence": active,
            "graph_suggestions": suggested,
            "working_set": working_refs,
            "evidence_conditioned_control": compact_control,
            "candidate_details": details,
            "recent_messages": recent_messages,
            "recent_tool_results": recent_tools,
            "budget": budget,
            "context_metrics": context_metrics,
        }
        workflow_capsule = ""
        if isinstance(workflow, dict) and workflow:
            workflow_capsule = (
                "<workflow-state>\n"
                "This controller-owned state is durable and overrides stale conversational plans.\n"
                + json.dumps(workflow, ensure_ascii=False, indent=2)
                + "\n</workflow-state>\n"
            )
        return (
            workflow_capsule
            + "<virtual-project-context>\n"
            "This is a task-scoped view over durable project knowledge. Graph suggestions are not verified facts. "
            "Use artifact_ref to reopen an externalized raw result only when necessary.\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
            + "\n</virtual-project-context>"
        )

    def _bounded_memory(self) -> dict[str, Any]:
        memory = self.memory.to_dict()
        limit = self.config.max_memory_items_per_field
        for key, value in list(memory.items()):
            if isinstance(value, list) and len(value) > limit:
                memory[key] = value[-limit:]
        return memory

    def _durable_instructions(self, messages: list[dict]) -> list[str]:
        durable: list[str] = []
        first_user = next((message for message in messages if message.get("role") == "user"), None)
        if first_user is not None:
            content = _message_text(first_user).strip()
            if content:
                durable.append(content)
        for message in messages:
            if message.get("role") != "user":
                continue
            content = _message_text(message).strip()
            if "<verified-skill" in content and content not in durable:
                durable.append(content)
        result: list[str] = []
        remaining = self.config.max_durable_instruction_chars
        for content in durable:
            if remaining <= 0:
                break
            bounded = content[:remaining]
            result.append(bounded)
            remaining -= len(bounded)
        return result

    def _recent_messages(
        self,
        messages: list[dict],
        durable_instructions: list[str],
    ) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for message in reversed(messages):
            role = str(message.get("role", message.get("type", "")))
            if role in {"system", "tool", "function_call_output", "exit"}:
                continue
            if message.get("extra", {}).get("virtual_context"):
                continue
            content = _message_text(message).strip()
            if not content or content == self.original_task or content in durable_instructions:
                continue
            if len(content) > 700:
                content = content[:676] + "... message truncated ..."
            results.append({"role": role or "unknown", "content": content})
            if len(results) >= self.config.max_recent_messages:
                break
        return list(reversed(results))

    @staticmethod
    def _stable_system_message(messages: list[dict]) -> dict:
        for message in messages:
            if message.get("role") == "system":
                return {key: value for key, value in message.items() if key != "extra"}
        return {"role": "system", "content": "You are a software engineering agent."}

    def _emit(self, event: str, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, component="context", **data)


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", message.get("output", ""))
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _summarize_tool_result(content: str, *, exception_info: str, limit: int) -> str:
    text = content.strip()
    if exception_info:
        text = f"{exception_info}\n{text}".strip()
    if not text:
        return "Tool completed without textual output."
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    selected = lines[:12]
    if len(lines) > 16:
        selected.extend(lines[-4:])
    summary = "\n".join(selected)
    if len(summary) > limit:
        summary = summary[: max(0, limit - 24)] + "\n... summary truncated ..."
    return summary


def _important_ranges(content: str) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for match in RANGE_PATTERN.finditer(content):
        key = (
            match.group("path").replace("\\", "/"),
            int(match.group("line")),
            int(match.group("column") or 0),
        )
        if key in seen:
            continue
        seen.add(key)
        ranges.append({"path": key[0], "line": key[1], "column": key[2] or None})
        if len(ranges) >= 20:
            break
    return ranges


def _extract_paths(value: str) -> list[str]:
    return list(dict.fromkeys(match.group("path").replace("\\", "/") for match in PATH_PATTERN.finditer(value)))


def _command_category(command: str) -> str:
    lowered = command.casefold()
    if any(token in lowered for token in ("-runTests".casefold(), "editmode", "playmode", "compile", "dotnet test", "unityvalidator")):
        return "validation"
    if any(token in lowered for token in ("set-content", "add-content", "out-file", "writealltext", "apply_patch", "move-item", "remove-item")):
        return "write"
    if any(token in lowered for token in ("get-content", "select-string", "type ", "gc ")):
        return "read"
    if any(token in lowered for token in ("rg ", "ripgrep", "get-childitem", "gci ", "dir ")):
        return "search"
    return "other"


def _bounded_json(value: dict[str, Any], limit: int) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) <= limit:
        return value
    return {
        "id": value.get("id", ""),
        "kind": value.get("kind", ""),
        "name": value.get("name", ""),
        "path": value.get("path", ""),
        "detail_truncated": True,
        "detail_preview": encoded[:limit],
    }


def _same_path(left: str, right: str) -> bool:
    return left.replace("\\", "/").casefold() == right.replace("\\", "/").casefold()
