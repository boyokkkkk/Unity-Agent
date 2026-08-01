from __future__ import annotations

import json
import re
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from game_agent.context import ContextAssembler, EvidenceStatus
from game_agent.context import EvidenceLedger

from .control import EvidenceActionCompiler
from .diagnosis import DiagnosisRecord
from .exposure import ToolExposure, select_tool_exposure
from .mutation import AciConfig, UnityMutationExecutor
from .query import StructuredQueryExecutor
from .resolver import GraphResolver
from .progress import ProgressEventType
from .schemas import (
    CANDIDATE_TOOL_NAMES,
    CONTROL_TOOL_NAMES,
    MUTATION_TOOL_NAMES,
    QUERY_TOOL_NAMES,
    WORKFLOW_TOOL_NAMES,
)
from .workflow import (
    GLOBAL_SEARCH_TOOLS,
    GRAPH_EXPANSION_TOOLS,
    ReviewRecord,
    TaskPlan,
    WorkflowPhase,
    WorkflowState,
)


@dataclass
class PendingChange:
    transaction_id: str
    tool: str
    checkpoint_id: str
    changed_paths: list[str]
    authorized_paths: list[str]
    diff_ref: str
    transaction_status: str
    script_change: bool
    diagnostics_complete: bool = False
    reload_complete: bool = False
    validation_complete: bool = False
    required_validation_modes: list[str] = field(default_factory=list)
    completed_validation_modes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def stage(self) -> str:
        if not self.diagnostics_complete:
            return "static_diagnostics"
        if self.script_change and not self.reload_complete:
            return "recompile_or_hot_reload"
        if not self.validation_complete:
            return "runtime_validation"
        return "complete"


class UnityAciController:
    """Gate Unity mutations behind evidence, checkpoints, diagnostics, and validation."""

    def __init__(
        self,
        context: ContextAssembler,
        *,
        project_root: Path,
        artifact_root: Path | None = None,
        config: AciConfig | dict[str, Any] | None = None,
        query_executor: StructuredQueryExecutor | None = None,
        mutation_executor: UnityMutationExecutor | None = None,
    ) -> None:
        self.context = context
        self.project_root = project_root.resolve()
        self.artifact_root = artifact_root.resolve() if artifact_root is not None else None
        self.config = config if isinstance(config, AciConfig) else AciConfig(**(config or {}))
        self.query_executor = query_executor or StructuredQueryExecutor(
            context,
            project_root=project_root,
            artifact_root=artifact_root,
        )
        self.mutation_executor = mutation_executor or UnityMutationExecutor(
            project_root=project_root,
            artifact_root=artifact_root,
            config=self.config,
        )
        self.action_compiler = EvidenceActionCompiler(
            context,
            project_root=project_root,
        )
        self.workflow: WorkflowState | None = self._new_workflow()
        self.resolver = GraphResolver(
            context,
            self.workflow.frontier if self.workflow is not None else self.action_compiler.context.working_set,
        ) if self.workflow is not None else None
        self.pending: PendingChange | None = None
        self.completed: list[dict[str, Any]] = []
        self.blocked_actions = 0

    def reset(self) -> None:
        self.pending = None
        self.completed = []
        self.blocked_actions = 0
        self.action_compiler.reset()
        self.workflow = self._new_workflow()
        self.resolver = GraphResolver(self.context, self.workflow.frontier) if self.workflow else None
        if self.workflow is not None:
            self.workflow.seed_frontier(self.context.working_set.entries.values())

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = str(action.get("tool", ""))
        workflow_block = self._guard_workflow_action(tool, action.get("arguments", {}))
        if workflow_block is not None:
            return workflow_block
        if tool in CANDIDATE_TOOL_NAMES:
            return self._execute_candidate_read(action)
        if tool == "task_plan_submit":
            return self._execute_plan(action.get("arguments", {}))
        if tool in {"diagnosis_submit", "diagnosis_revise"}:
            return self._execute_diagnosis(tool, action.get("arguments", {}))
        if tool == "workflow_review":
            return self._execute_review()
        decision = self.action_compiler.before_action(action)
        if not decision.allowed:
            self.blocked_actions += 1
            return self.action_compiler.replan_output(
                action,
                reason=decision.reason,
            )
        if tool in QUERY_TOOL_NAMES:
            output = self.query_executor.execute(action)
            evidence_ids = self._record_output_evidence(output)
            self._consume_query(tool, output)
            self.action_compiler.observe(action, output)
            if self.workflow is not None and tool in GLOBAL_SEARCH_TOOLS | GRAPH_EXPANSION_TOOLS:
                structured = output.get("extra", {}).get("structured", {})
                phase_before = self.workflow.phase
                improved = self.workflow.observe_search(
                    tool, structured if isinstance(structured, dict) else {}
                )
                if improved and evidence_ids:
                    self.workflow.progress.record(
                        ProgressEventType.FRONTIER_IMPROVED,
                        phase_before=phase_before.value,
                        phase_after=self.workflow.phase.value,
                        evidence_ids=evidence_ids,
                        details={"tool": tool, "frontier_size": len(self.workflow.frontier)},
                    )
                output.setdefault("extra", {})["workflow_state"] = self.workflow.public_state()
            return output
        if tool in MUTATION_TOOL_NAMES:
            blocked = self._guard_mutation(tool, action.get("arguments", {}))
            if blocked:
                return blocked
            execution_action = dict(action)
            if self.workflow is not None:
                execution_action["_authorized_paths"] = sorted(self.workflow.authorized_paths)
                # Inject evidence artifacts for mutation tools
                if tool == "unity_script_patch":
                    arguments = dict(execution_action.get("arguments", {}))
                    execution_action["arguments"] = arguments
                    if isinstance(arguments, dict):
                        requested_nodes = {
                            str(value) for value in arguments.get("evidence_node_ids", []) if value
                        }
                        approved = next(
                            (
                                mutation
                                for mutation in self.workflow.diagnosis.proposed_mutations
                                if self.workflow.frontier.get(mutation.target) is not None
                                and self.workflow.frontier.get(mutation.target).node_id in requested_nodes
                            ),
                            None,
                        ) if self.workflow.diagnosis is not None else None
                        if approved is not None and approved.evidence_id:
                            arguments.setdefault("evidence_id", approved.evidence_id)
                        # Try to inject evidence_artifact_path if not already provided
                        if "evidence_artifact_path" not in arguments and self.workflow.evidence_artifacts:
                            # Match by evidence_id or by path
                            evidence_id = arguments.get("evidence_id", "")
                            if evidence_id and evidence_id in self.workflow.evidence_artifacts:
                                arguments["evidence_artifact_path"] = self.workflow.evidence_artifacts[evidence_id]
            output = self.mutation_executor.execute(execution_action)
            self.action_compiler.observe(action, output)
            if self._succeeded(output):
                evidence_ids = self._record_output_evidence(output)
                extra = output.get("extra", {})
                transaction = extra.get("mutation_transaction", {})
                self.pending = PendingChange(
                    transaction_id=str(transaction.get("transaction_id", "")) or uuid.uuid4().hex[:12],
                    tool=tool,
                    checkpoint_id=str(extra.get("checkpoint_id", "")),
                    changed_paths=[str(value) for value in extra.get("changed_paths", [])],
                    authorized_paths=[
                        str(value) for value in transaction.get("authorized_paths", [])
                    ],
                    diff_ref=str(extra.get("mutation_diff", "")),
                    transaction_status=str(transaction.get("status", "")),
                    script_change=tool in {"unity_script_patch", "unity_execute_csharp"},
                    required_validation_modes=list(self.config.required_validation_modes),
                )
                if self.workflow is not None:
                    phase_before = self.workflow.phase
                    self.workflow.observe_mutation(
                        changed_paths_authorized=(
                            self.pending.transaction_status == "applied"
                            and not transaction.get("unauthorized_paths", [])
                        ),
                    )
                    self.workflow.progress.record(
                        ProgressEventType.MUTATION_APPLIED,
                        phase_before=phase_before.value,
                        phase_after=self.workflow.phase.value,
                        evidence_ids=evidence_ids,
                        details={"tool": tool, "changed_paths": self.pending.changed_paths},
                    )
                output.setdefault("extra", {})["execution_protocol"] = self.protocol_state()
            elif self.workflow is not None:
                extra = output.setdefault("extra", {})
                structured = extra.get("structured", {})
                failure_message = str(
                    extra.get("message")
                    or output.get("exception_info")
                    or (structured.get("message", "") if isinstance(structured, dict) else "")
                    or "Mutation did not produce an applied change."
                )
                phase_before = self.workflow.phase
                paths = [
                    str(value) for value in extra.get("changed_paths", [])
                    if value
                ] if isinstance(extra.get("changed_paths"), list) else []

                # Extract diagnostic information from mutation failure
                diagnostic = extra.get("diagnostic") if isinstance(extra, dict) else None

                self.workflow.observe_mutation_failure(
                    tool=tool,
                    message=failure_message,
                    paths=paths,
                    diagnostic=diagnostic,
                )
                self.workflow.progress.record(
                    ProgressEventType.MUTATION_FAILED,
                    phase_before=phase_before.value,
                    phase_after=self.workflow.phase.value,
                    evidence_ids=[],
                    details={"tool": tool, "message": failure_message, "diagnostic": diagnostic},
                    advances=False,
                )
                extra["workflow_recovery"] = {
                    "phase": self.workflow.phase.value,
                    "required_next_actions": self.workflow.required_next_actions(),
                    "reason": failure_message,
                    "stage_directive": self.workflow.stage_directive,
                }
            return output
        if tool in CONTROL_TOOL_NAMES:
            blocked = self._guard_control(tool, action.get("arguments", {}))
            if blocked:
                return blocked
            output = self.mutation_executor.execute(action)
            evidence_ids = self._record_output_evidence(output)
            phase_before = self.workflow.phase if self.workflow is not None else None
            self._consume_control(tool, output)
            self.action_compiler.observe(action, output)
            self._record_validation_progress(
                tool,
                output,
                evidence_ids=evidence_ids,
                phase_before=phase_before,
            )
            output.setdefault("extra", {})["execution_protocol"] = self.protocol_state()
            return output
        return self._blocked(tool, "unknown_aci_tool", f"Unknown ACI tool: {tool}")

    def replan_repeated(self, action: dict[str, Any]) -> dict[str, Any]:
        self.blocked_actions += 1
        return self.action_compiler.replan_output(
            action,
            reason="The action repeated after prior evidence or a prior replan; choose an admissible alternative.",
        )

    def guard_submission(self) -> dict[str, Any] | None:
        if self.pending is not None:
            return self._blocked(
                "submit",
                "execution_protocol_incomplete",
                f"Cannot submit while checkpoint {self.pending.checkpoint_id} awaits {self.pending.stage}.",
            )
        if self.workflow is None:
            return None
        missing = self.workflow.submission.unmet()
        if missing:
            guard = (
                "mutation_required" if "mutation_count" in missing
                else "review_required" if "final_review_passed" in missing
                else "submission_contract_incomplete"
            )
            return self._blocked(
                "submit",
                guard,
                "Submission contract is incomplete: " + ", ".join(missing) + ".",
            )
        self.workflow.phase = WorkflowPhase.SUBMIT
        return None

    def guard_general_shell(self) -> dict[str, Any]:
        return self._blocked(
            "powershell",
            "general_shell_forbidden",
            "General Shell is disabled in workflow mode; use structured query and mutation tools.",
        )

    def automatic_submission(self) -> str | None:
        if self.pending is not None or self.workflow is None:
            return None
        if self.workflow.phase != WorkflowPhase.SUBMIT or self.workflow.submission.unmet():
            return None
        changed_paths = sorted({
            str(path)
            for transaction in self.completed
            for path in transaction.get("changed_paths", [])
        })
        modes = sorted({
            str(mode)
            for transaction in self.completed
            for mode in transaction.get("completed_validation_modes", [])
        })
        diagnosis = self.workflow.diagnosis
        diagnosis_text = diagnosis.symptom if diagnosis is not None else "Accepted no-change diagnosis"
        return (
            "Controller verified the complete submission contract. "
            f"Diagnosis: {diagnosis_text}. "
            f"Changed paths: {', '.join(changed_paths) or 'none'}. "
            f"Validation passed: diagnostics, compile, {', '.join(modes) or 'required tests'}."
        )

    def tool_exposure(self) -> ToolExposure:
        pending_stage = self.pending.stage if self.pending is not None else ""
        return select_tool_exposure(
            phase=self.context.phase,
            unresolved_slot_ids=(
                str(slot.get("id", ""))
                for slot in self.action_compiler.open_slots()
            ),
            working_paths=(
                entry.path for entry in self.context.working_set.entries.values()
            ),
            pending_stage=pending_stage,
            enabled=self.config.dynamic_tool_exposure_enabled,
            workflow=self.workflow,
        )

    def protocol_state(self) -> dict[str, Any]:
        required_next_actions = self._required_next_actions()
        workflow_state = self.workflow.public_state() if self.workflow is not None else {}
        if required_next_actions:
            workflow_state["required_next_actions"] = required_next_actions
        return {
            "pending": asdict(self.pending) | {"stage": self.pending.stage} if self.pending else None,
            "completed_transactions": len(self.completed),
            "blocked_actions": self.blocked_actions,
            "tool_exposure": self.tool_exposure().to_dict(),
            "workflow": workflow_state,
            **self.action_compiler.state(),
            **self.mutation_executor.metrics(),
        }

    def _required_next_actions(self) -> list[str]:
        if self.pending is None:
            return self.workflow.required_next_actions() if self.workflow is not None else []
        if self.pending.stage == "static_diagnostics":
            return ["Call code_diagnostics once for the changed C# file."]
        if self.pending.stage == "recompile_or_hot_reload":
            return ["Static diagnostics are complete. Call unity_recompile now."]
        if self.pending.stage == "runtime_validation":
            remaining = sorted(
                set(self.pending.required_validation_modes)
                - set(self.pending.completed_validation_modes)
            )
            return [
                "Compile is complete. Call unity_validate for pending mode(s): "
                + ", ".join(remaining)
            ]
        return []

    def metrics(self) -> dict[str, Any]:
        return self.protocol_state()

    def _guard_mutation(self, tool: str, args: Any) -> dict[str, Any] | None:
        if self.pending is not None:
            return self._blocked(
                tool,
                "previous_change_unverified",
                f"Checkpoint {self.pending.checkpoint_id} must finish {self.pending.stage} before another mutation.",
            )
        if not isinstance(args, dict):
            return self._blocked(tool, "invalid_arguments", "Arguments must be an object.")
        node_ids = args.get("evidence_node_ids", [])
        if not isinstance(node_ids, list) or not node_ids:
            return self._blocked(tool, "location_evidence_required", "evidence_node_ids must be non-empty.")
        requested = {str(value) for value in node_ids if value}
        if self.workflow is not None:
            diagnosis = self.workflow.diagnosis
            if diagnosis is None or diagnosis.status != "accepted":
                return self._blocked(
                    tool,
                    "diagnosis_required",
                    "Submit an accepted evidence-linked diagnosis before mutation.",
                )
            unauthorized = requested - self.workflow.authorized_targets
            if unauthorized:
                return self._blocked(
                    tool,
                    "mutation_target_unauthorized",
                    "Mutation evidence target(s) are outside the accepted diagnosis: "
                    + ", ".join(sorted(unauthorized))
                    + ". Revise the diagnosis first.",
                )
            try:
                target_paths = self.mutation_executor.resolve_target_paths(tool, args)
            except (OSError, ValueError, RuntimeError) as exc:
                return self._blocked(tool, "invalid_target_paths", str(exc))
            unauthorized_paths = {
                path for path in target_paths
                if path.replace("\\", "/").casefold() not in self.workflow.authorized_paths
            }
            if unauthorized_paths:
                return self._blocked(
                    tool,
                    "mutation_target_unauthorized",
                    "Mutation path(s) are outside the accepted diagnosis: "
                    + ", ".join(sorted(unauthorized_paths))
                    + ". Revise the diagnosis first.",
                )
            if tool == "unity_script_patch":
                approved = next(
                    (
                        mutation
                        for mutation in diagnosis.proposed_mutations
                        if self.workflow.frontier.get(mutation.target) is not None
                        and self.workflow.frontier.get(mutation.target).node_id in requested
                    ),
                    None,
                )
                if approved is None:
                    return self._blocked(
                        tool,
                        "mutation_anchor_missing",
                        "No diagnosis-approved script patch anchor exists for the requested target.",
                    )
                if (
                    str(args.get("old_text", "")) != approved.old_text
                    or str(args.get("new_text", "")) != approved.new_text
                ):
                    return self._blocked(
                        tool,
                        "mutation_deviates_from_diagnosis",
                        "unity_script_patch old_text/new_text must exactly match the accepted diagnosis. "
                        "Read the target and revise the diagnosis instead of guessing a new patch.",
                    )
        store = self.context.project_store
        stale = requested.intersection(store.dirty_nodes) if store is not None else set()
        if stale:
            return self._blocked(
                tool,
                "stale_target_read_required",
                f"Rebuild the project graph and read stale target node(s) again: {', '.join(sorted(stale))}.",
            )
        active = [
            evidence
            for evidence in self.context.evidence.active()
            if requested.intersection(evidence.node_ids)
        ]
        located = {
            node_id
            for evidence in active
            for node_id in evidence.node_ids
            if node_id in requested
        }
        if self.config.require_location_evidence and located != requested:
            missing = sorted(requested - located)
            return self._blocked(
                tool,
                "location_evidence_required",
                f"No project-graph localization evidence exists for node(s): {', '.join(missing)}.",
            )
        read = {
            node_id
            for evidence in active
            if evidence.status in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}
            for node_id in evidence.node_ids
            if node_id in requested
        }
        if self.config.require_target_read and read != requested:
            missing = sorted(requested - read)
            return self._blocked(
                tool,
                "target_read_required",
                f"Read the target with unity_object_read, unity_asset_read, or code_file_read first: {', '.join(missing)}.",
            )
        return None

    def _guard_control(self, tool: str, args: Any) -> dict[str, Any] | None:
        if self.pending is None:
            return self._blocked(tool, "no_pending_change", "No checkpointed change is awaiting verification.")
        if tool in {"unity_recompile", "unity_hot_reload"}:
            if not self.pending.diagnostics_complete:
                return self._blocked(
                    tool,
                    "static_diagnostics_required",
                    "Run code_diagnostics successfully before reload.",
                )
            if not self.pending.script_change:
                return self._blocked(tool, "reload_not_required", "The pending typed asset change does not require reload.")
        if tool == "unity_validate":
            if not self.pending.diagnostics_complete:
                return self._blocked(
                    tool,
                    "static_diagnostics_required",
                    "Run code_diagnostics successfully before Unity validation.",
                )
            if self.pending.script_change and not self.pending.reload_complete:
                return self._blocked(
                    tool,
                    "reload_required",
                    "Run unity_recompile or a successful unity_hot_reload before validation.",
                )
            modes = set(args.get("modes", [])) if isinstance(args, dict) else set()
            remaining = set(self.pending.required_validation_modes) - set(self.pending.completed_validation_modes)
            if not modes.intersection(remaining):
                return self._blocked(
                    tool,
                    "required_validation_modes",
                    f"Validation must include at least one pending mode: {', '.join(sorted(remaining))}.",
                )
        return None

    def _consume_query(self, tool: str, output: dict[str, Any]) -> None:
        if self.pending is None or tool != "code_diagnostics" or not self._succeeded(output):
            return
        structured = output.get("extra", {}).get("structured", {})
        if structured.get("status") == "unavailable":
            return
        diagnostics = structured.get("diagnostics", [])
        if any(str(item.get("severity", "")).casefold() == "error" for item in diagnostics):
            return
        self.pending.diagnostics_complete = True
        if self.workflow is not None:
            self.workflow.observe_diagnostics_passed()

    def _consume_control(self, tool: str, output: dict[str, Any]) -> None:
        if self.pending is None or not self._succeeded(output):
            return
        if tool in {"unity_recompile", "unity_hot_reload"}:
            self.pending.reload_complete = True
            if self.workflow is not None:
                self.workflow.observe_compile_passed()
        elif tool == "unity_validate":
            modes = [str(value) for value in output.get("extra", {}).get("validation_modes", [])]
            self.pending.completed_validation_modes = list(
                dict.fromkeys([*self.pending.completed_validation_modes, *modes])
            )
            required = set(self.pending.required_validation_modes)
            self.pending.validation_complete = required <= set(self.pending.completed_validation_modes)
        if self.pending.stage == "complete":
            state = asdict(self.pending) | {"stage": "complete", "completed_at": time.time()}
            self.completed.append(state)
            self.context.record_verified_fact(
                f"Checkpoint {self.pending.checkpoint_id} completed diagnostics, reload policy, and "
                f"{', '.join(self.pending.required_validation_modes)} validation.",
                sources=[f"checkpoint:{self.pending.checkpoint_id}"],
                runtime_verified=True,
            )
            self.pending = None
            if self.workflow is not None:
                self.workflow.observe_validation_complete()
                self._perform_review()

    def _new_workflow(self) -> WorkflowState | None:
        if not self.config.workflow_enabled:
            return None
        return WorkflowState.create(
            global_search_limit=self.config.global_search_limit,
            graph_expansion_limit=self.config.graph_expansion_limit,
            frontier_size=self.config.candidate_frontier_size,
            mutation_required=self.config.mutation_required,
            required_causal_roles=(
                {"event_source", "controller", "ui"}
                if self.config.require_causal_role_evidence else set()
            ),
        )

    def _guard_workflow_action(self, tool: str, arguments: Any = None) -> dict[str, Any] | None:
        if self.workflow is None:
            return None
        allowed, reason = self.workflow.before_action(
            tool,
            arguments if isinstance(arguments, dict) else {},
        )
        if not allowed:
            self.workflow.blocked_actions += 1
            return self._blocked(tool, "workflow_phase_or_budget", reason)
        exposed = set(self.tool_exposure().tool_names)
        if tool not in exposed:
            self.workflow.blocked_actions += 1
            return self._blocked(
                tool,
                "workflow_tool_unavailable",
                f"{tool} is not allowed during {self.workflow.phase.value}; choose a required next action.",
            )
        return None

    def _execute_candidate_read(self, action: dict[str, Any]) -> dict[str, Any]:
        if self.workflow is None or self.resolver is None:
            return self._blocked("candidate_read", "workflow_disabled", "candidate_read requires workflow mode.")
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            return self._blocked("candidate_read", "invalid_arguments", "Arguments must be an object.")
        candidate_id = str(arguments.get("candidate_id", "")).upper()
        view = str(arguments.get("view", "preview"))
        try:
            canonical, ref = self.resolver.candidate_read_action(arguments)
        except ValueError as exc:
            return self._blocked("candidate_read", "candidate_resolution_failed", str(exc))
        output = self.query_executor.execute(canonical)
        self.action_compiler.observe(canonical, output)
        extra = output.setdefault("extra", {})
        claim = str(extra.get("evidence_claim", "")).strip()
        sources = [str(value) for value in extra.get("evidence_sources", []) if value]
        evidence_ids = self._record_output_evidence(output)
        if claim and not evidence_ids:
            evidence_ids.append(EvidenceLedger.id_for(claim, sources or [f"candidate:{candidate_id}"]))
        succeeded = self._succeeded(output) and bool(claim) and bool(evidence_ids)
        if succeeded:
            phase_before = self.workflow.phase
            advanced = self.workflow.observe_candidate_read(
                candidate_id,
                level=view,
                evidence_ids=list(dict.fromkeys(evidence_ids)),
            )
            if advanced:
                self.workflow.progress.record(
                    ProgressEventType.IMPLEMENTATION_READ,
                    phase_before=phase_before.value,
                    phase_after=self.workflow.phase.value,
                    evidence_ids=evidence_ids,
                    details={"candidate_id": candidate_id, "view": view, "path": ref.path},
                )

        # P0 Fix: 传递evidence artifact信息
        evidence_artifact_path = str(extra.get("evidence_artifact_path", "")).strip() or None
        evidence_artifact_sha256 = str(extra.get("evidence_artifact_sha256", "")).strip() or None

        extra.update(
            candidate_id=candidate_id,
            resolved_entity=asdict(ref),
            resolved_tool=canonical["tool"],
            evidence_ids=list(dict.fromkeys(evidence_ids)),
            workflow_state=self.workflow.public_state(),
        )

        # P0 Fix: 如果底层工具返回了artifact信息，传递给上层
        if evidence_artifact_path:
            extra["evidence_artifact_path"] = evidence_artifact_path
        if evidence_artifact_sha256:
            extra["evidence_artifact_sha256"] = evidence_artifact_sha256

        return output

    def _execute_plan(self, arguments: Any) -> dict[str, Any]:
        if self.workflow is None:
            return self._blocked("task_plan_submit", "workflow_disabled", "Planning requires workflow mode.")
        if not isinstance(arguments, dict):
            return self._blocked("task_plan_submit", "invalid_arguments", "Arguments must be an object.")
        plan = TaskPlan.from_arguments(arguments)
        gaps: list[str] = []
        for name, value in (
            ("objective", plan.objective),
            ("hypotheses", plan.hypotheses),
            ("required_evidence", plan.required_evidence),
            ("success_criteria", plan.success_criteria),
        ):
            if not value:
                gaps.append(f"{name} must be non-empty")
        required_modes = {
            "compile",
            *[str(value).casefold() for value in self.config.required_validation_modes],
        }
        missing_modes = required_modes - set(plan.validation_plan)
        if missing_modes:
            gaps.append("validation_plan is missing: " + ", ".join(sorted(missing_modes)))
        if gaps:
            return self._blocked(
                "task_plan_submit",
                "plan_incomplete",
                "; ".join(gaps),
            )
        self.workflow.accept_plan(plan)
        payload = {
            "status": "accepted",
            "plan": asdict(plan),
            "workflow_state": self.workflow.public_state(),
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": 0,
            "exception_info": "",
            "extra": {
                "aci": True,
                "aci_workflow": True,
                "workflow_tool": "task_plan_submit",
                "structured": payload,
                "workflow_state": self.workflow.public_state(),
            },
        }

    def _execute_review(self) -> dict[str, Any]:
        assert self.workflow is not None
        review = self._perform_review()
        contract = self.workflow.submission
        gaps = review.gaps
        payload = {
            "status": review.status,
            "review": asdict(review),
            "submission_contract": asdict(contract),
            "workflow_state": self.workflow.public_state(),
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": 0 if not gaps else -2,
            "exception_info": "" if not gaps else "; ".join(gaps),
            "extra": {
                "aci": True,
                "aci_workflow": True,
                "workflow_tool": "workflow_review",
                "blocked": bool(gaps),
                "guard": "" if not gaps else "review_failed",
                "structured": payload,
                "workflow_state": self.workflow.public_state(),
            },
        }

    def _perform_review(self) -> ReviewRecord:
        assert self.workflow is not None
        contract = self.workflow.submission
        changed_paths = sorted({
            str(path)
            for transaction in self.completed
            for path in transaction.get("changed_paths", [])
        })
        authorized_paths = sorted(self.workflow.authorized_paths)
        validation_modes = sorted({
            str(mode)
            for transaction in self.completed
            for mode in transaction.get("completed_validation_modes", [])
        })
        gaps = [value for value in contract.unmet() if value != "final_review_passed"]
        unauthorized = [
            path for path in changed_paths
            if not self._path_authorized(path, authorized_paths)
        ]
        if unauthorized:
            gaps.append("actual diff exceeds diagnosis authorization: " + ", ".join(unauthorized))
        if not changed_paths and contract.mutation_count:
            gaps.append("completed mutation transactions contain no actual diff")
        review = ReviewRecord(
            status="rejected" if gaps else "accepted",
            changed_paths=changed_paths,
            authorized_paths=authorized_paths,
            validation_modes=validation_modes,
            gaps=list(dict.fromkeys(gaps)),
        )
        self.workflow.record_review(review)
        return review

    def _execute_diagnosis(self, tool: str, arguments: Any) -> dict[str, Any]:
        if self.workflow is None:
            return self._blocked(tool, "workflow_disabled", "Diagnosis tools require workflow mode.")
        if not isinstance(arguments, dict):
            return self._blocked(tool, "invalid_arguments", "Arguments must be an object.")
        if tool == "diagnosis_submit" and self.workflow.diagnosis_history:
            return self._blocked(tool, "diagnosis_revision_required", "Use diagnosis_revise to preserve history.")
        if tool == "diagnosis_revise" and not self.workflow.diagnosis_history:
            return self._blocked(tool, "diagnosis_missing", "Use diagnosis_submit for the first diagnosis.")
        revision = self._project_revision()
        proposed = DiagnosisRecord.from_arguments(
            arguments,
            version=len(self.workflow.diagnosis_history) + 1,
            repository_revision=revision,
            evidence_ledger=self.context.evidence,
        )
        gaps, missing_candidates, authorized_targets, authorized_paths = self._diagnosis_gaps(proposed)
        status = "rejected" if gaps else "accepted"
        diagnosis = proposed.with_decision(status=status, gaps=gaps)
        phase_before = self.workflow.phase
        if gaps:
            self.workflow.reject_diagnosis(
                diagnosis,
                missing_candidate_ids=missing_candidates,
            )
        else:
            self.workflow.accept_diagnosis(
                diagnosis,
                authorized_targets=authorized_targets,
                authorized_paths=authorized_paths,
            )
            self.workflow.progress.record(
                ProgressEventType.DIAGNOSIS_ACCEPTED,
                phase_before=phase_before.value,
                phase_after=self.workflow.phase.value,
                evidence_ids=diagnosis.evidence_ids(),
                details={
                    "diagnosis_version": diagnosis.version,
                    "authorized_candidate_ids": sorted(
                        mutation.target for mutation in diagnosis.proposed_mutations
                    ),
                },
            )
        payload = {
            "status": status,
            "diagnosis": diagnosis.to_dict(),
            "gaps": gaps,
            "required_next_actions": self.workflow.required_next_actions(),
            "workflow_state": self.workflow.public_state(),
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": 0 if not gaps else -2,
            "exception_info": "" if not gaps else "; ".join(gaps),
            "extra": {
                "aci": True,
                "aci_workflow": True,
                "workflow_tool": tool,
                "blocked": bool(gaps),
                "guard": "" if not gaps else "diagnosis_incomplete",
                "structured": payload,
                "workflow_state": self.workflow.public_state(),
            },
        }

    def _diagnosis_gaps(
        self,
        diagnosis: DiagnosisRecord,
    ) -> tuple[list[str], set[str], set[str], set[str]]:
        assert self.workflow is not None
        gaps: list[str] = []
        missing_candidates: set[str] = set()
        missing_roles = self.workflow.missing_causal_roles()
        if missing_roles:
            gaps.append(
                "causal evidence roles have not been read: "
                + ", ".join(sorted(missing_roles))
            )
            missing_candidates.update(
                candidate.candidate_id
                for candidate in self.workflow.frontier.candidates()
                if candidate.role in missing_roles and candidate.read_level == "unread"
            )
        if not diagnosis.symptom:
            gaps.append("symptom must be non-empty")
        roots = [self.workflow.frontier.get(value) for value in diagnosis.root_targets]
        for candidate_id, candidate in zip(diagnosis.root_targets, roots):
            if candidate is None:
                gaps.append(f"root target {candidate_id} is not in the candidate frontier")
            elif candidate.read_level == "unread":
                gaps.append(f"root target {candidate_id} has not been read")
                missing_candidates.add(candidate_id)
            elif candidate.role == "test":
                gaps.append(f"root target {candidate_id} is test code, not an implementation root")
        if not diagnosis.causal_chain:
            gaps.append("causal_chain must contain at least one evidence-linked claim")
        current_revision = self._project_revision()
        evidence_by_id = {item.id: item for item in self.context.evidence.active()}
        verified_evidence = []
        for claim_index, claim in enumerate(diagnosis.causal_chain, start=1):
            if not claim.statement:
                gaps.append(f"causal claim {claim_index} has no statement")
            if not claim.evidence_ids:
                gaps.append(f"causal claim {claim_index} has no evidence_ids")
            for evidence_id in claim.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    gaps.append(f"evidence {evidence_id} does not exist or was rejected")
                    continue
                if evidence.status not in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}:
                    gaps.append(f"evidence {evidence_id} is not source/runtime verified")
                    continue
                if current_revision and evidence.repository_revision != current_revision:
                    gaps.append(f"evidence {evidence_id} belongs to a different repository revision")
                    continue
                dirty = set(evidence.node_ids).intersection(
                    self.context.project_store.dirty_nodes if self.context.project_store is not None else {}
                )
                if dirty:
                    gaps.append(f"evidence {evidence_id} references stale node(s): {', '.join(sorted(dirty))}")
                    continue
                verified_evidence.append(evidence)
        graph = self.context.project_store.graph if self.context.project_store is not None else None
        implementation_covered = False
        for evidence in verified_evidence:
            for node_id in evidence.node_ids:
                node = graph.nodes.get(node_id) if graph is not None else None
                if node is not None and node.path.casefold().endswith(".cs") and "test" not in node.path.casefold():
                    implementation_covered = True
                    break
        if not implementation_covered:
            gaps.append("causal evidence does not cover non-test implementation code")
        if not diagnosis.proposed_mutations:
            gaps.append("proposed_mutations must not be empty")
        authorized_targets: set[str] = set()
        authorized_paths: set[str] = set()
        root_ids = set(diagnosis.root_targets)
        for mutation in diagnosis.proposed_mutations:
            candidate = self.workflow.frontier.get(mutation.target)
            if candidate is None:
                gaps.append(f"mutation target {mutation.target} is not in the candidate frontier")
                continue
            if mutation.target not in root_ids:
                gaps.append(f"mutation target {mutation.target} is not declared as a root target")
            if candidate.read_level == "unread":
                gaps.append(f"mutation target {mutation.target} has not been read")
                missing_candidates.add(mutation.target)
            if not mutation.operation:
                gaps.append(f"mutation target {mutation.target} has no operation")
            if candidate.path.casefold().endswith(".cs"):
                self._validate_script_mutation_anchor(
                    diagnosis,
                    mutation,
                    candidate,
                    evidence_by_id=evidence_by_id,
                    gaps=gaps,
                )
            authorized_targets.add(candidate.node_id)
            authorized_paths.add(candidate.path)
            for path in mutation.target_paths:
                normalized = path.replace("\\", "/")
                if not normalized.casefold().startswith("assets/"):
                    gaps.append(f"authorized target path must be under Assets/: {path}")
                else:
                    authorized_paths.add(normalized)
        required_modes = {"compile", *[str(value).casefold() for value in self.config.required_validation_modes]}
        missing_modes = required_modes - set(diagnosis.validation_plan)
        if missing_modes:
            gaps.append("validation_plan is missing: " + ", ".join(sorted(missing_modes)))
        if diagnosis.remaining_uncertainty:
            gaps.append("remaining critical uncertainty: " + "; ".join(diagnosis.remaining_uncertainty))
        return list(dict.fromkeys(gaps)), missing_candidates, authorized_targets, authorized_paths

    def _validate_script_mutation_anchor(
        self,
        diagnosis: DiagnosisRecord,
        mutation,
        candidate,
        *,
        evidence_by_id: dict[str, Any],
        gaps: list[str],
    ) -> None:
        """Require a diagnosis to authorize an exact, evidence-grounded C# replacement."""
        label = f"mutation target {mutation.target}"
        if not mutation.evidence_id:
            gaps.append(f"{label} requires evidence_id for a C# edit")
            return
        evidence = evidence_by_id.get(mutation.evidence_id)
        if evidence is None:
            gaps.append(f"{label} evidence {mutation.evidence_id} does not exist or was rejected")
            return
        if mutation.evidence_id not in diagnosis.evidence_ids():
            gaps.append(f"{label} evidence_id must also ground a causal claim")
        if evidence.status not in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}:
            gaps.append(f"{label} evidence {mutation.evidence_id} is not source/runtime verified")
        if candidate.node_id not in evidence.node_ids:
            gaps.append(f"{label} evidence {mutation.evidence_id} does not cover the target candidate")
        if not mutation.old_text:
            gaps.append(f"{label} requires non-empty old_text for a C# edit")
            return
        if mutation.old_text == mutation.new_text:
            gaps.append(f"{label} new_text must differ from old_text")
        try:
            target = (self.project_root / candidate.path).resolve()
            if target != self.project_root and self.project_root not in target.parents:
                raise ValueError("target path escapes the project")
            source_text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            gaps.append(f"{label} source could not be verified: {exc}")
            return
        occurrences = source_text.replace("\r\n", "\n").count(
            mutation.old_text.replace("\r\n", "\n")
        )
        if occurrences != 1:
            gaps.append(
                f"{label} old_text must occur exactly once in verified target source; found {occurrences}"
            )
            return
        normalized_source = source_text.replace("\r\n", "\n")
        normalized_old = mutation.old_text.replace("\r\n", "\n")
        normalized_new = mutation.new_text.replace("\r\n", "\n")
        patched_source = normalized_source.replace(normalized_old, normalized_new, 1)
        gaps.extend(
            f"{label} {gap}"
            for gap in self._csharp_patch_preflight(
                normalized_source,
                normalized_old,
                normalized_new,
                patched_source,
            )
        )

    @classmethod
    def _csharp_patch_preflight(
        cls,
        source_text: str,
        old_text: str,
        new_text: str,
        patched_source: str,
    ) -> list[str]:
        """Reject structurally invalid or source-incompatible C# before edit authorization."""
        gaps: list[str] = []
        declaration = re.fullmatch(
            r"\s*(?:(?:public|internal|private|protected|abstract|sealed|static|partial)\s+)*"
            r"(?:class|struct|interface|enum|record)\s+[A-Za-z_]\w*(?:\s*:[^\r\n{]+)?\s*",
            old_text,
        )
        if declaration and ("\n" in new_text or "{" in new_text or "}" in new_text):
            gaps.append(
                "old_text is a type declaration, not a local edit site; anchor the replacement inside the relevant method body"
            )

        source_braces = cls._csharp_brace_balance(source_text)
        patched_braces = cls._csharp_brace_balance(patched_source)
        if source_braces == 0 and patched_braces != 0:
            gaps.append(
                f"replacement makes C# braces unbalanced (net balance {patched_braces:+d})"
            )

        original_methods = Counter(cls._csharp_method_signatures(source_text))
        patched_methods = Counter(cls._csharp_method_signatures(patched_source))
        duplicates = sorted(
            signature
            for signature, count in patched_methods.items()
            if count > 1 and count > original_methods.get(signature, 0)
        )
        if duplicates:
            gaps.append(
                "replacement introduces duplicate method signature(s): "
                + ", ".join(f"{name}/{arity}" for name, arity in duplicates)
            )

        original_qualified = set(re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", source_text))
        introduced_state_members = sorted(
            f"{owner}.{member}"
            for owner, member in set(re.findall(r"\b([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b", new_text))
            if re.search(rf"\benum\s+{re.escape(owner)}\b", source_text)
            and (owner, member) not in original_qualified
        )
        if introduced_state_members:
            gaps.append(
                "replacement references enum members absent from the verified target source: "
                + ", ".join(introduced_state_members)
            )
        return list(dict.fromkeys(gaps))

    @staticmethod
    def _csharp_method_signatures(source_text: str) -> list[tuple[str, int]]:
        pattern = re.compile(
            r"\b(?:public|private|protected|internal)\s+"
            r"(?:(?:static|virtual|override|abstract|async|sealed|extern|new|partial)\s+)*"
            r"(?:[A-Za-z_]\w*(?:\s*<[^>{};]+>)?(?:\[\])?[?.]?\s+)?"
            r"(?P<name>[A-Za-z_]\w*)\s*\((?P<params>[^()]*)\)\s*(?:\{|=>)",
            re.MULTILINE,
        )
        signatures: list[tuple[str, int]] = []
        for match in pattern.finditer(source_text):
            parameters = match.group("params").strip()
            arity = 0 if not parameters else parameters.count(",") + 1
            signatures.append((match.group("name"), arity))
        return signatures

    @staticmethod
    def _csharp_brace_balance(source_text: str) -> int:
        balance = 0
        state = "code"
        index = 0
        while index < len(source_text):
            char = source_text[index]
            following = source_text[index + 1] if index + 1 < len(source_text) else ""
            if state == "code":
                if char == "/" and following == "/":
                    state = "line_comment"
                    index += 1
                elif char == "/" and following == "*":
                    state = "block_comment"
                    index += 1
                elif char == '"':
                    state = "string"
                elif char == "'":
                    state = "char"
                elif char == "{":
                    balance += 1
                elif char == "}":
                    balance -= 1
                    if balance < 0:
                        return balance
            elif state == "line_comment":
                if char == "\n":
                    state = "code"
            elif state == "block_comment":
                if char == "*" and following == "/":
                    state = "code"
                    index += 1
            elif state in {"string", "char"}:
                quote = '"' if state == "string" else "'"
                if char == "\\":
                    index += 1
                elif char == quote:
                    state = "code"
            index += 1
        return balance

    def _record_output_evidence(self, output: dict[str, Any]) -> list[str]:
        extra = output.get("extra", {})
        claim = str(extra.get("evidence_claim", "")).strip()
        if not claim:
            return []
        sources = [str(value) for value in extra.get("evidence_sources", []) if value]
        node_ids = [str(value) for value in extra.get("node_ids", []) if value]
        try:
            status = EvidenceStatus(str(extra.get("evidence_status", "observed")))
        except ValueError:
            status = EvidenceStatus.OBSERVED
        evidence = self.context.evidence.add(
            claim,
            status=status,
            sources=sources or ["aci:controller"],
            node_ids=node_ids,
            confidence=0.9 if status in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED} else 0.65,
            repository_revision=self._project_revision(),
        )
        return [evidence.id]

    def _record_validation_progress(
        self,
        tool: str,
        output: dict[str, Any],
        *,
        evidence_ids: list[str],
        phase_before: WorkflowPhase | None,
    ) -> None:
        if self.workflow is None or phase_before is None or not evidence_ids:
            return
        modes = [str(value).casefold() for value in output.get("extra", {}).get("validation_modes", [])]
        succeeded = self._succeeded(output)
        if not succeeded:
            self.workflow.progress.record(
                ProgressEventType.VALIDATION_FAILED,
                phase_before=phase_before.value,
                phase_after=self.workflow.phase.value,
                evidence_ids=evidence_ids,
                details={"tool": tool, "modes": modes},
                advances=False,
            )
            return
        event_types = {
            "compile": ProgressEventType.COMPILE_PASSED,
            "editmode": ProgressEventType.EDITMODE_PASSED,
            "playmode": ProgressEventType.PLAYMODE_PASSED,
        }
        for mode in modes:
            event_type = event_types.get(mode)
            if event_type is not None:
                self.workflow.progress.record(
                    event_type,
                    phase_before=phase_before.value,
                    phase_after=self.workflow.phase.value,
                    evidence_ids=evidence_ids,
                    details={"tool": tool, "mode": mode},
                )

    def semantic_progress_version(self) -> int:
        return self.workflow.progress.version if self.workflow is not None else 0

    def handle_no_progress(self):
        return self.workflow.handle_no_progress() if self.workflow is not None else None

    def _project_revision(self) -> str:
        store = self.context.project_store
        return store.version.project_revision if store is not None else ""

    @staticmethod
    def _path_authorized(path: str, authorized_paths: list[str]) -> bool:
        normalized = path.replace("\\", "/").lstrip("./").casefold()
        for authorized in authorized_paths:
            candidate = authorized.replace("\\", "/").lstrip("./").casefold()
            if normalized in {candidate, f"{candidate}.meta"}:
                return True
            parent = Path(candidate).parent.as_posix()
            if normalized.endswith(".meta") and parent not in {"", ".", "assets"}:
                if normalized == f"{parent}.meta":
                    return True
        return False

    @staticmethod
    def _succeeded(output: dict[str, Any]) -> bool:
        structured = output.get("extra", {}).get("structured", {})
        return int(output.get("returncode", -1)) == 0 and structured.get("status") != "unavailable"

    def _blocked(self, tool: str, code: str, message: str) -> dict[str, Any]:
        self.blocked_actions += 1
        payload = {
            "status": "blocked",
            "tool": tool,
            "guard": code,
            "message": message,
            "execution_protocol": self.protocol_state(),
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": -2,
            "exception_info": message,
            "extra": {
                "aci": True,
                "blocked": True,
                "guard": code,
                "structured": payload,
            },
        }
