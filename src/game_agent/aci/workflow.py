from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .candidate import CandidateFrontier
from .diagnosis import DiagnosisRecord, ProposedMutation
from .progress import ProgressLedger


class WorkflowPhase(StrEnum):
    PLAN = "plan"
    EXPLORE = "explore"
    INSPECT = "inspect"
    DIAGNOSE = "diagnose"
    PREPARE_EDIT = "prepare_edit"
    EDIT = "edit"
    VALIDATE = "validate"
    REVIEW = "review"
    SUBMIT = "submit"


GLOBAL_SEARCH_TOOLS = frozenset(
    {"code_symbol_search", "unity_asset_search", "unity_object_search"}
)
GRAPH_EXPANSION_TOOLS = frozenset({"code_find_references", "unity_ref_search"})


@dataclass(slots=True)
class SearchBudget:
    enabled: bool = True
    global_limit: int = 2
    global_used: int = 0
    graph_expansion_limit: int = 3
    graph_expansion_used: int = 0

    def available(self, tool: str) -> bool:
        if not self.enabled:
            return True
        if tool in GLOBAL_SEARCH_TOOLS:
            return self.global_used < self.global_limit
        if tool in GRAPH_EXPANSION_TOOLS:
            return self.graph_expansion_used < self.graph_expansion_limit
        return True

    def consume(self, tool: str) -> None:
        if tool in GLOBAL_SEARCH_TOOLS:
            self.global_used += 1
        elif tool in GRAPH_EXPANSION_TOOLS:
            self.graph_expansion_used += 1


@dataclass(slots=True)
class SubmissionContract:
    plan_accepted: bool = False
    diagnosis_accepted: bool = False
    mutation_required: bool = True
    mutation_count: int = 0
    no_change_diagnosis_accepted: bool = False
    changed_paths_authorized: bool = False
    diagnostics_passed: bool = False
    compile_passed: bool = False
    required_tests_passed: bool = False
    critical_uncertainties_resolved: bool = False
    validation_complete: bool = False
    final_review_passed: bool = False

    def unmet(self) -> list[str]:
        missing: list[str] = []
        if not self.plan_accepted:
            missing.append("plan_accepted")
        if not self.diagnosis_accepted and not self.no_change_diagnosis_accepted:
            missing.append("diagnosis_accepted")
        if self.mutation_required and self.mutation_count < 1 and not self.no_change_diagnosis_accepted:
            missing.append("mutation_count")
        if self.mutation_count and not self.changed_paths_authorized:
            missing.append("changed_paths_authorized")
        if self.mutation_count and not self.diagnostics_passed:
            missing.append("diagnostics_passed")
        if self.mutation_count and not self.compile_passed:
            missing.append("compile_passed")
        if self.mutation_count and not self.required_tests_passed:
            missing.append("required_tests_passed")
        if not self.critical_uncertainties_resolved:
            missing.append("critical_uncertainties_resolved")
        if not self.final_review_passed:
            missing.append("final_review_passed")
        return missing


@dataclass(slots=True)
class TaskPlan:
    objective: str
    hypotheses: list[str]
    required_evidence: list[str]
    success_criteria: list[str]
    validation_plan: list[str]

    @classmethod
    def from_arguments(cls, arguments: dict[str, Any]) -> "TaskPlan":
        return cls(
            objective=str(arguments.get("objective", "")).strip(),
            hypotheses=[str(value).strip() for value in arguments.get("hypotheses", []) if str(value).strip()],
            required_evidence=[str(value).strip() for value in arguments.get("required_evidence", []) if str(value).strip()],
            success_criteria=[str(value).strip() for value in arguments.get("success_criteria", []) if str(value).strip()],
            validation_plan=[str(value).casefold() for value in arguments.get("validation_plan", []) if str(value).strip()],
        )


@dataclass(slots=True)
class ReviewRecord:
    status: str
    changed_paths: list[str]
    authorized_paths: list[str]
    validation_modes: list[str]
    gaps: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class NoProgressDecision:
    terminate: bool
    message: str
    phase_before: WorkflowPhase
    phase_after: WorkflowPhase


@dataclass(slots=True)
class WorkflowState:
    phase: WorkflowPhase
    search_budget: SearchBudget
    frontier: CandidateFrontier
    submission: SubmissionContract
    plan: TaskPlan | None = None
    reviews: list[ReviewRecord] = field(default_factory=list)
    progress: ProgressLedger = field(default_factory=ProgressLedger)
    diagnosis: DiagnosisRecord | None = None
    diagnosis_history: list[DiagnosisRecord] = field(default_factory=list)
    authorized_targets: set[str] = field(default_factory=set)
    authorized_paths: set[str] = field(default_factory=set)
    evidence_artifacts: dict[str, str] = field(default_factory=dict)
    missing_evidence_candidate_ids: set[str] = field(default_factory=set)
    stage_directive: str = ""
    last_mutation_failure: dict[str, Any] | None = None
    no_progress_interventions: dict[str, int] = field(default_factory=dict)
    blocked_actions: int = 0
    required_causal_roles: set[str] = field(default_factory=set)
    causal_fact_matrix: dict[str, Any] = field(default_factory=dict)
    prepared_mutations: list[ProposedMutation] = field(default_factory=list)
    prepared_patch_token: str = ""
    patch_status: str = "not_prepared"
    patch_gaps: list[str] = field(default_factory=list)
    compile_repair_attempts: int = 0
    evidence_recovery_enabled: bool = True

    @classmethod
    def create(
        cls,
        *,
        global_search_limit: int,
        graph_expansion_limit: int,
        frontier_size: int,
        mutation_required: bool,
        required_causal_roles: set[str] | None = None,
        bounded_search_enabled: bool = True,
        evidence_recovery_enabled: bool = True,
    ) -> "WorkflowState":
        return cls(
            phase=WorkflowPhase.PLAN,
            search_budget=SearchBudget(
                enabled=bounded_search_enabled,
                global_limit=max(0, global_search_limit),
                graph_expansion_limit=max(0, graph_expansion_limit),
            ),
            frontier=CandidateFrontier(
                max_size=frontier_size,
                retained_roles=set(required_causal_roles or set()),
            ),
            submission=SubmissionContract(mutation_required=mutation_required),
            required_causal_roles=set(required_causal_roles or set()),
            evidence_recovery_enabled=evidence_recovery_enabled,
        )

    def accept_plan(self, plan: TaskPlan) -> None:
        self.plan = plan
        self.submission.plan_accepted = True
        self.phase = WorkflowPhase.EXPLORE
        self._maybe_lock_frontier()

    def seed_frontier(self, entries: Any) -> None:
        self.frontier.add_working_set(entries)
        self._maybe_lock_frontier()

    def before_action(self, tool: str, arguments: dict[str, Any] | None = None) -> tuple[bool, str]:
        if tool in GLOBAL_SEARCH_TOOLS:
            if self.phase != WorkflowPhase.EXPLORE:
                return False, f"{tool} is unavailable after the candidate frontier is locked."
            if not self.search_budget.available(tool):
                self.phase = WorkflowPhase.INSPECT
                return False, f"Search budget for {tool} is exhausted; inspect a candidate instead."
        if tool in GRAPH_EXPANSION_TOOLS:
            if self.phase not in {WorkflowPhase.EXPLORE, WorkflowPhase.INSPECT}:
                return False, f"{tool} is unavailable during {self.phase.value}."
            if not self.search_budget.available(tool):
                return False, f"Graph expansion budget for {tool} is exhausted."
        if tool == "candidate_read" and self.phase == WorkflowPhase.DIAGNOSE:
            requested = str((arguments or {}).get("candidate_id", "")).upper()
            if self.missing_evidence_candidate_ids and requested not in self.missing_evidence_candidate_ids:
                allowed = ", ".join(sorted(self.missing_evidence_candidate_ids))
                return False, f"Diagnosis evidence collection is restricted to: {allowed}."
        if tool == "candidate_read":
            requested = str((arguments or {}).get("candidate_id", "")).upper()
            level = str((arguments or {}).get("view", "preview"))
            candidate = self.frontier.get(requested)
            if candidate is not None and not self.frontier.read_would_advance(requested, level=level):
                return False, (
                    f"{requested} is already read at {candidate.read_level}; repeated reads do not advance "
                    "the workflow. Follow required_next_actions."
                )
        return True, ""

    def observe_search(self, tool: str, structured: dict[str, Any]) -> bool:
        self.search_budget.consume(tool)
        rows = structured.get("results", []) if isinstance(structured, dict) else []
        query = str(structured.get("query", "")) if isinstance(structured, dict) else ""
        improved = self.frontier.add_rows(rows if isinstance(rows, list) else [], query=query)
        self._maybe_lock_frontier()
        return improved

    def observe_candidate_read(
        self,
        candidate_id: str,
        *,
        level: str,
        evidence_ids: list[str],
    ) -> bool:
        advanced = self.frontier.mark_read(candidate_id, level=level, evidence_ids=evidence_ids)
        if not advanced:
            return False
        self.missing_evidence_candidate_ids.discard(candidate_id.upper())
        self.phase = (
            WorkflowPhase.INSPECT
            if self.missing_causal_roles()
            else WorkflowPhase.DIAGNOSE
        )
        return True

    def read_causal_roles(self) -> set[str]:
        return {
            candidate.role
            for candidate in self.frontier.candidates()
            if candidate.read_level != "unread"
        }

    def missing_causal_roles(self) -> set[str]:
        return self.required_causal_roles - self.read_causal_roles()

    def accept_diagnosis(
        self,
        diagnosis: DiagnosisRecord,
        *,
        authorized_targets: set[str],
        authorized_paths: set[str],
        prepare_edit: bool = False,
    ) -> None:
        self.diagnosis = diagnosis
        self.diagnosis_history.append(diagnosis)
        self.authorized_targets = set(authorized_targets)
        self.authorized_paths = {path.replace("\\", "/").casefold() for path in authorized_paths}
        self.evidence_artifacts = dict(diagnosis.evidence_artifacts)
        self.missing_evidence_candidate_ids.clear()
        self.stage_directive = ""
        self.last_mutation_failure = None
        self.prepared_mutations = []
        self.prepared_patch_token = ""
        self.patch_status = "not_prepared"
        self.patch_gaps = []
        self.compile_repair_attempts = 0
        self.submission.diagnosis_accepted = True
        self.submission.critical_uncertainties_resolved = not diagnosis.remaining_uncertainty
        self.phase = WorkflowPhase.PREPARE_EDIT if prepare_edit else WorkflowPhase.EDIT

    def accept_patch(
        self,
        mutation: ProposedMutation,
        *,
        authorized_target: str,
        authorized_path: str,
        patch_token: str = "",
    ) -> None:
        self.prepared_mutations = [mutation]
        self.prepared_patch_token = patch_token
        self.authorized_targets = {authorized_target}
        self.authorized_paths = {authorized_path.replace("\\", "/").casefold()}
        self.patch_status = "prepared"
        self.patch_gaps = []
        self.stage_directive = ""
        self.phase = WorkflowPhase.EDIT

    def reject_patch(self, gaps: list[str]) -> None:
        self.prepared_mutations = []
        self.prepared_patch_token = ""
        self.authorized_targets.clear()
        self.authorized_paths.clear()
        self.patch_status = "rejected"
        self.patch_gaps = list(gaps)
        self.stage_directive = (
            "Patch preparation failed while the accepted diagnosis remains valid. "
            "Revise only patch_prepare using a controller-provided AST fact and exemplar."
        )
        self.phase = WorkflowPhase.PREPARE_EDIT

    def observe_compile_failure(self, message: str, *, retry_allowed: bool) -> None:
        """Return to patch preparation while retaining the evidence-backed diagnosis."""
        self.compile_repair_attempts += 1
        self.prepared_mutations = []
        self.prepared_patch_token = ""
        self.authorized_targets.clear()
        self.authorized_paths.clear()
        self.patch_status = "compile_rejected"
        self.patch_gaps = [message]
        self.submission.mutation_count = max(0, self.submission.mutation_count - 1)
        self.submission.changed_paths_authorized = False
        self.submission.diagnostics_passed = False
        self.submission.compile_passed = False
        self.submission.required_tests_passed = False
        self.submission.validation_complete = False
        self.submission.final_review_passed = False
        instruction = (
            "Keep the accepted causal diagnosis and call patch_prepare again using the compiler feedback: "
            if retry_allowed else
            "The compile-repair budget is exhausted; call diagnosis_revise before another patch: "
        )
        self.stage_directive = (
            "The patched source was restored from its checkpoint after compile failure. "
            + instruction
            + message
        )
        self.phase = WorkflowPhase.PREPARE_EDIT

    def reject_diagnosis(
        self,
        diagnosis: DiagnosisRecord,
        *,
        missing_candidate_ids: set[str],
    ) -> None:
        self.diagnosis = diagnosis
        self.diagnosis_history.append(diagnosis)
        self.authorized_targets.clear()
        self.authorized_paths.clear()
        self.submission.diagnosis_accepted = False
        self.submission.critical_uncertainties_resolved = False
        self.missing_evidence_candidate_ids = {value.upper() for value in missing_candidate_ids}
        self.evidence_artifacts = dict(diagnosis.evidence_artifacts)
        patch_gaps = [
            gap for gap in diagnosis.gaps
            if gap.casefold().startswith("mutation target ")
            and any(
                marker in gap.casefold()
                for marker in (
                    "old_text", "new_text", "replacement", "type declaration",
                    "duplicate method", "enum member",
                )
            )
        ]
        if patch_gaps:
            target_paths = sorted({
                candidate.path
                for mutation in diagnosis.proposed_mutations
                if (candidate := self.frontier.get(mutation.target)) is not None
            })
            artifact_refs = sorted(set(diagnosis.evidence_artifacts.values()))
            recovery_read = (
                f'Call artifact_read("{artifact_refs[0]}") to recover the already-verified source text'
                if artifact_refs
                else "Re-read the exact target with code_file_read"
            )
            self.stage_directive = (
                "Diagnosis patch preflight failed for "
                + (", ".join(target_paths) if target_paths else "the target")
                + f". {recovery_read}, then call diagnosis_revise using a local old_text/new_text "
                "copied from the relevant method context. Do not guess or reread an unchanged SHA."
            )
            self.phase = WorkflowPhase.INSPECT
            return
        # A semantic uncertainty is not the same thing as an unread root
        # candidate.  When the diagnosis names such a gap, staying in
        # DIAGNOSE leaves only diagnosis_revise exposed while making it
        # impossible to obtain the evidence needed for that revision.  Return
        # to the bounded inspection stage so the model can consume the locked
        # frontier or expand references, without reopening global search.
        if not self.missing_evidence_candidate_ids and any(
            gap.casefold().startswith("remaining critical uncertainty:")
            for gap in diagnosis.gaps
        ):
            self.phase = WorkflowPhase.INSPECT
        else:
            self.stage_directive = ""
            self.phase = WorkflowPhase.DIAGNOSE

    def observe_mutation(self, *, changed_paths_authorized: bool) -> None:
        # A prepared patch is a single-use capability.  Once its exact mutation
        # has been applied, remove both the token and mutation description so a
        # later model turn cannot replay stale edit authority.
        self.prepared_mutations = []
        self.prepared_patch_token = ""
        self.submission.mutation_count += 1
        self.submission.changed_paths_authorized = changed_paths_authorized
        self.submission.diagnostics_passed = False
        self.submission.compile_passed = False
        self.submission.required_tests_passed = False
        self.submission.validation_complete = False
        self.submission.final_review_passed = False
        self.phase = WorkflowPhase.VALIDATE

    def observe_mutation_failure(
        self,
        *,
        tool: str,
        message: str,
        paths: list[str] | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        """Force failed edits through a fresh localization/diagnosis cycle with evidence-based recovery guidance."""
        if self.prepared_mutations and self.diagnosis is not None and self.diagnosis.status == "accepted":
            self.prepared_mutations = []
            self.prepared_patch_token = ""
            self.patch_status = "rejected"
            self.patch_gaps = [message]
            self.authorized_targets.clear()
            self.authorized_paths.clear()
            self.last_mutation_failure = {
                "tool": tool,
                "message": message,
                "paths": list(paths or []),
                "diagnostic": diagnostic or {},
            }
            self.stage_directive = (
                "The prepared patch failed; call patch_prepare again for the accepted diagnosis."
                if not self.evidence_recovery_enabled else
                "The prepared patch failed, but the evidence-backed diagnosis remains accepted. "
                "Call patch_prepare again with the same causal fact and a corrected insertion."
            )
            self.phase = WorkflowPhase.PREPARE_EDIT
            return
        self.submission.diagnosis_accepted = False
        self.submission.critical_uncertainties_resolved = False
        self.authorized_targets.clear()
        self.authorized_paths.clear()
        self.last_mutation_failure = {
            "tool": tool,
            "message": message,
            "paths": list(paths or []),
            "diagnostic": diagnostic or {},
        }

        if not self.evidence_recovery_enabled:
            self.stage_directive = (
                "Mutation failed; re-read the target source and revise the diagnosis before retrying."
            )
            self.phase = WorkflowPhase.INSPECT
            return

        # Provide specific recovery guidance based on diagnostic
        error_code = diagnostic.get("error_code") if diagnostic else None
        recovery_hint = diagnostic.get("recovery_hint") if diagnostic else None
        evidence_artifact_path = diagnostic.get("evidence_artifact_path") if diagnostic else None

        if error_code == "old_text_not_found_in_evidence" and evidence_artifact_path:
            self.stage_directive = (
                f"Mutation failed: old_text not found in evidence artifact. "
                f"Use artifact_read(\"{evidence_artifact_path}\") to inspect the exact evidence content, "
                f"then call diagnosis_revise with corrected proposed_mutations.old_text/new_text."
            )
        elif error_code in {"old_text_not_found_in_evidence", "old_text_ambiguous_in_evidence"}:
            target_path = diagnostic.get("path", "") if diagnostic else ""
            self.stage_directive = (
                f"Mutation anchor no longer matches {target_path or 'the target source'}. "
                "Read the exact target with code_file_read (or its evidence with artifact_read), then call "
                "diagnosis_revise with corrected proposed_mutations.old_text/new_text."
            )
        elif error_code in ("file_changed_old_text_gone", "file_changed_old_text_ambiguous"):
            target_path = diagnostic.get("path", "") if diagnostic else ""
            self.stage_directive = (
                f"Mutation failed: target file has changed since diagnosis (error: {error_code}). "
                f"Re-read {target_path or 'the current file'} with code_file_read, then call diagnosis_revise "
                f"with proposed_mutations.old_text/new_text matching the current content."
            )
        elif recovery_hint:
            self.stage_directive = f"Mutation failed: {message}. Recovery guidance: {recovery_hint}"
        else:
            self.stage_directive = (
                "Mutation failed; re-read or expand the target evidence, then revise the diagnosis. "
                + message
            )

        self.phase = WorkflowPhase.INSPECT

    def observe_diagnostics_passed(self) -> None:
        self.submission.diagnostics_passed = True

    def observe_compile_passed(self) -> None:
        self.submission.compile_passed = True

    def observe_validation_complete(self) -> None:
        self.submission.required_tests_passed = True
        self.submission.validation_complete = True
        self.submission.final_review_passed = False
        self.phase = WorkflowPhase.REVIEW

    def record_review(self, review: ReviewRecord) -> None:
        self.reviews.append(review)
        self.submission.final_review_passed = review.status == "accepted"
        self.phase = WorkflowPhase.SUBMIT if review.status == "accepted" else WorkflowPhase.EDIT

    def public_state(self, *, compact: bool = False) -> dict[str, Any]:
        payload = {
            "phase": self.phase.value,
            "plan": asdict(self.plan) if self.plan is not None else None,
            "search_budget": asdict(self.search_budget),
            "candidate_frontier": self.frontier.public_candidates(),
            "diagnosis": self.diagnosis.to_dict() if self.diagnosis is not None else None,
            "diagnosis_versions": len(self.diagnosis_history),
            "progress": self.progress.to_dict(),
            "authorized_candidate_ids": [
                candidate.candidate_id
                for candidate in self.frontier.candidates()
                if candidate.node_id in self.authorized_targets
            ],
            "authorized_paths": sorted(self.authorized_paths),
            "missing_evidence_candidate_ids": sorted(self.missing_evidence_candidate_ids),
            "required_causal_roles": sorted(self.required_causal_roles),
            "read_causal_roles": sorted(self.read_causal_roles()),
            "missing_causal_roles": sorted(self.missing_causal_roles()),
            "causal_fact_matrix": self.causal_fact_matrix,
            "patch_status": self.patch_status,
            "patch_gaps": self.patch_gaps,
            "compile_repair_attempts": self.compile_repair_attempts,
            "prepared_mutations": [asdict(item) for item in self.prepared_mutations],
            "prepared_patch_token": self.prepared_patch_token,
            "stage_directive": self.stage_directive,
            "submission_contract": asdict(self.submission),
            "reviews": [asdict(review) for review in self.reviews],
            "required_next_actions": self.required_next_actions(),
            "forbidden": self.forbidden_actions(),
        }
        if compact:
            payload["causal_fact_matrix"] = self._compact_causal_fact_matrix()
            payload["progress"] = {
                "version": self.progress.version,
                "events": [item.to_dict() for item in self.progress.events[-4:]],
            }
            if self.diagnosis is not None:
                payload["diagnosis"] = {
                    "version": self.diagnosis.version,
                    "symptom": self.diagnosis.symptom,
                    "root_targets": self.diagnosis.root_targets,
                    "status": self.diagnosis.status,
                    "remaining_uncertainty": self.diagnosis.remaining_uncertainty,
                    "causal_chain": [
                        {
                            "subject": claim.subject,
                            "predicate": claim.predicate,
                            "object": claim.object,
                            "polarity": claim.polarity,
                            "fact_ids": claim.fact_ids,
                            "negative_evidence": (
                                asdict(claim.negative_evidence)
                                if claim.negative_evidence is not None else None
                            ),
                        }
                        for claim in self.diagnosis.causal_chain
                    ],
                }
            if self.phase in {
                WorkflowPhase.PREPARE_EDIT,
                WorkflowPhase.EDIT,
                WorkflowPhase.VALIDATE,
                WorkflowPhase.REVIEW,
                WorkflowPhase.SUBMIT,
            }:
                matrix = self.causal_fact_matrix if isinstance(self.causal_fact_matrix, dict) else {}
                cited_fact_ids = {
                    fact_id
                    for claim in (self.diagnosis.causal_chain if self.diagnosis is not None else [])
                    for fact_id in claim.fact_ids
                }
                selected_facts = [
                    fact
                    for slot in matrix.get("slots", {}).values()
                    if isinstance(slot, dict)
                    for fact in slot.get("facts", [])
                    if isinstance(fact, dict) and fact.get("fact_id") in cited_fact_ids
                ]
                payload["causal_fact_matrix"] = {
                    "graph_revision": matrix.get("graph_revision", ""),
                    "status": "diagnosis_locked",
                    "selected_facts": selected_facts,
                }
                payload["prepared_mutations"] = []
        return payload

    def _compact_causal_fact_matrix(self) -> dict[str, Any]:
        matrix = self.causal_fact_matrix if isinstance(self.causal_fact_matrix, dict) else {}
        slots = matrix.get("slots", {}) if isinstance(matrix.get("slots", {}), dict) else {}

        def facts(slot: str) -> list[dict[str, Any]]:
            value = slots.get(slot, {})
            rows = value.get("facts", []) if isinstance(value, dict) else []
            return [item for item in rows if isinstance(item, dict)]

        missing_publications = [
            item for item in facts("event_publication")
            if item.get("polarity") == "absent"
        ]
        if not missing_publications:
            return matrix
        writers = {str(item.get("subject", "")) for item in missing_publications}
        events = {str(item.get("object", "")) for item in missing_publications}
        publications = [
            item for item in facts("event_publication")
            if item in missing_publications or str(item.get("object", "")) in events
        ]
        trigger_subscriptions = [
            item for item in facts("trigger_subscription")
            if str(item.get("subject", "")) in writers
        ]
        observer_subscriptions = [
            item for item in facts("observer_subscription")
            if str(item.get("object", "")) in events
        ]
        observer_handlers = {
            str(item.get("subject", "")) for item in observer_subscriptions
        }
        declared_events = events | {
            str(item.get("object", "")) for item in trigger_subscriptions
        }
        selected = {
            "event_declaration": [
                item for item in facts("event_declaration")
                if str(item.get("object", "")) in declared_events
            ],
            "trigger_subscription": trigger_subscriptions,
            "state_write": [
                item for item in facts("state_write")
                if str(item.get("subject", "")) in writers
            ],
            "event_publication": publications,
            "observer_subscription": observer_subscriptions,
            "observer_effect": [
                item for item in facts("observer_effect")
                if str(item.get("subject", "")) in observer_handlers
            ],
        }
        return {
            "graph_revision": matrix.get("graph_revision", ""),
            "scope_paths": matrix.get("scope_paths", []),
            "slots": {
                name: {
                    "status": (
                        "absent" if any(item.get("polarity") == "absent" for item in rows)
                        else "present" if rows else "unknown"
                    ),
                    "facts": rows,
                }
                for name, rows in selected.items()
            },
        }

    def required_next_actions(self) -> list[str]:
        if self.phase == WorkflowPhase.PLAN:
            return ["Submit a structured task plan before repository exploration."]
        if self.phase == WorkflowPhase.EXPLORE:
            return ["Use a bounded global search to form a candidate frontier."]
        if self.phase == WorkflowPhase.INSPECT:
            if self.last_mutation_failure or self.stage_directive:
                return [self.stage_directive or (
                    "Read the failed mutation target, then revise the diagnosis with an exact patch anchor."
                )]
            missing_roles = self.missing_causal_roles()
            if missing_roles:
                role_candidates = [
                    f"{candidate.candidate_id} ({candidate.role})"
                    for candidate in self.frontier.candidates()
                    if candidate.role in missing_roles and candidate.read_level == "unread"
                ]
                if role_candidates:
                    return [
                        "Read causal evidence for every missing role before diagnosis: "
                        + ", ".join(role_candidates)
                    ]
                return [
                    "Expand graph references to find candidates for missing causal roles: "
                    + ", ".join(sorted(missing_roles))
                ]
            ids = [
                candidate.candidate_id for candidate in self.frontier.candidates()
                if candidate.read_level == "unread"
            ]
            return [f"Read one candidate with candidate_read: {', '.join(ids)}"] if ids else [
                "No candidate is available; report localization failure."
            ]
        if self.phase == WorkflowPhase.DIAGNOSE:
            if self.missing_evidence_candidate_ids:
                return [
                    "Read only the diagnosis evidence candidates: "
                    + ", ".join(sorted(self.missing_evidence_candidate_ids))
                ]
            unread = [
                candidate.candidate_id for candidate in self.frontier.candidates()
                if candidate.read_level == "unread"
            ]
            if unread:
                return [
                    "Submit an evidence-linked diagnosis when the causal chain is supported; otherwise read one "
                    "already-retrieved candidate before diagnosing: " + ", ".join(unread)
                ]
            return ["Submit an evidence-linked diagnosis before mutation."]
        if self.phase == WorkflowPhase.PREPARE_EDIT:
            return [
                self.stage_directive
                or "Call patch_prepare using a controller causal fact, or a unique exact source anchor for a non-event C# repair."
            ]
        if self.phase == WorkflowPhase.EDIT:
            if self.prepared_patch_token:
                return [
                    "Call patch_apply with the controller-provided patch_token; do not copy patch text."
                ]
            return [self.stage_directive or "Apply one evidence-backed typed mutation to an authorized target."]
        if self.phase == WorkflowPhase.VALIDATE:
            return ["Complete diagnostics, reload policy, and required Unity validation."]
        if self.phase == WorkflowPhase.REVIEW:
            return ["Call workflow_review to compare the actual diff, authorization, validation, and success contract."]
        if self.phase == WorkflowPhase.SUBMIT:
            return ["Submit the verified result."]
        return ["Complete the current workflow contract."]

    def forbidden_actions(self) -> list[str]:
        if self.phase == WorkflowPhase.PLAN:
            return ["search", "read", "diagnosis", "mutation", "validation", "submit", "powershell"]
        if self.phase == WorkflowPhase.EXPLORE:
            return ["mutation", "submit", "powershell"]
        if self.phase == WorkflowPhase.INSPECT:
            return ["global_search", "mutation", "submit", "powershell"]
        if self.phase == WorkflowPhase.DIAGNOSE:
            return ["global_search", "relation_expansion", "mutation", "submit", "powershell"]
        if self.phase == WorkflowPhase.PREPARE_EDIT:
            return ["global_search", "relation_expansion", "mutation", "validation", "submit", "powershell"]
        if self.phase == WorkflowPhase.EDIT:
            return ["global_search", "submit", "powershell"]
        if self.phase == WorkflowPhase.VALIDATE:
            return ["search", "ordinary_mutation", "submit", "powershell"]
        if self.phase == WorkflowPhase.REVIEW:
            return ["search", "mutation", "powershell"]
        return ["all_except_submit"] if self.phase == WorkflowPhase.SUBMIT else []

    def handle_no_progress(self) -> NoProgressDecision:
        before = self.phase
        key = before.value
        count = self.no_progress_interventions.get(key, 0) + 1
        self.no_progress_interventions[key] = count
        terminate = False
        if before == WorkflowPhase.EXPLORE:
            self.phase = WorkflowPhase.INSPECT
            message = "Exploration produced no semantic progress; the existing candidate frontier is now locked."
        elif before == WorkflowPhase.INSPECT and self.stage_directive and count == 1:
            message = self.stage_directive
        elif before == WorkflowPhase.INSPECT:
            self.phase = WorkflowPhase.DIAGNOSE
            message = "Inspection stalled; submit the current evidence-linked diagnosis or identify a missing candidate."
        elif before == WorkflowPhase.DIAGNOSE and count == 1:
            unread = {
                candidate.candidate_id for candidate in self.frontier.candidates()
                if candidate.read_level == "unread"
            }
            if unread:
                self.missing_evidence_candidate_ids = unread
            message = "Diagnosis stalled; only explicitly missing candidate evidence may be read before diagnosis revision."
        elif before == WorkflowPhase.PREPARE_EDIT and count == 1:
            message = "Patch preparation stalled; use the AST anchor and repair exemplar from the accepted causal fact."
        elif before == WorkflowPhase.EDIT and count == 1:
            self.stage_directive = "Inspect the authorized diff or roll back the pending approach before another edit."
            message = self.stage_directive
        else:
            terminate = True
            message = (
                "Validation produced no new confirmed result; stop repeated validation and retain the last definite result."
                if before == WorkflowPhase.VALIDATE
                else f"No semantic progress remained during {before.value}."
            )
        return NoProgressDecision(
            terminate=terminate,
            message=message,
            phase_before=before,
            phase_after=self.phase,
        )

    def _maybe_lock_frontier(self) -> None:
        if self.phase == WorkflowPhase.PLAN:
            return
        high_confidence = [
            candidate for candidate in self.frontier.candidates()
            if candidate.score >= 0.65 and candidate.role != "test"
        ]
        enough_roles = (
            len(high_confidence) >= 3
            and len({candidate.role for candidate in high_confidence}) >= 2
        )
        budget_exhausted = self.search_budget.global_used >= self.search_budget.global_limit
        if enough_roles or budget_exhausted:
            self.phase = WorkflowPhase.INSPECT
