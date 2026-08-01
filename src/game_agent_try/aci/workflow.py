from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .candidate import CandidateFrontier
from .diagnosis import DiagnosisRecord
from .progress import ProgressLedger


class WorkflowPhase(StrEnum):
    PLAN = "plan"
    EXPLORE = "explore"
    INSPECT = "inspect"
    DIAGNOSE = "diagnose"
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
    global_limit: int = 2
    global_used: int = 0
    graph_expansion_limit: int = 3
    graph_expansion_used: int = 0

    def available(self, tool: str) -> bool:
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

    @classmethod
    def create(
        cls,
        *,
        global_search_limit: int,
        graph_expansion_limit: int,
        frontier_size: int,
        mutation_required: bool,
    ) -> "WorkflowState":
        return cls(
            phase=WorkflowPhase.PLAN,
            search_budget=SearchBudget(
                global_limit=max(0, global_search_limit),
                graph_expansion_limit=max(0, graph_expansion_limit),
            ),
            frontier=CandidateFrontier(max_size=frontier_size),
            submission=SubmissionContract(mutation_required=mutation_required),
        )

    def accept_plan(self, plan: TaskPlan) -> None:
        self.plan = plan
        self.submission.plan_accepted = True
        self.phase = WorkflowPhase.EXPLORE

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
            if not self.missing_evidence_candidate_ids:
                return False, "Candidate evidence is sufficient; submit or revise the diagnosis now."
            if requested not in self.missing_evidence_candidate_ids:
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
        self.phase = WorkflowPhase.DIAGNOSE
        return True

    def accept_diagnosis(
        self,
        diagnosis: DiagnosisRecord,
        *,
        authorized_targets: set[str],
        authorized_paths: set[str],
    ) -> None:
        self.diagnosis = diagnosis
        self.diagnosis_history.append(diagnosis)
        self.authorized_targets = set(authorized_targets)
        self.authorized_paths = {path.replace("\\", "/").casefold() for path in authorized_paths}
        self.evidence_artifacts = dict(diagnosis.evidence_artifacts)
        self.missing_evidence_candidate_ids.clear()
        self.stage_directive = ""
        self.last_mutation_failure = None
        self.submission.diagnosis_accepted = True
        self.submission.critical_uncertainties_resolved = not diagnosis.remaining_uncertainty
        self.phase = WorkflowPhase.EDIT

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
            self.stage_directive = (
                "Diagnosis patch preflight failed. Re-read the exact target"
                + (f" ({', '.join(target_paths)})" if target_paths else "")
                + " with code_file_read or read its evidence artifact with artifact_read, then call "
                "diagnosis_revise using a local old_text/new_text copied from the relevant method context."
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

    def public_state(self) -> dict[str, Any]:
        return {
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
            "stage_directive": self.stage_directive,
            "submission_contract": asdict(self.submission),
            "reviews": [asdict(review) for review in self.reviews],
            "required_next_actions": self.required_next_actions(),
            "forbidden": self.forbidden_actions(),
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
            ids = [candidate.candidate_id for candidate in self.frontier.candidates()]
            return [f"Read one candidate with candidate_read: {', '.join(ids)}"] if ids else [
                "No candidate is available; report localization failure."
            ]
        if self.phase == WorkflowPhase.DIAGNOSE:
            if self.missing_evidence_candidate_ids:
                return [
                    "Read only the diagnosis evidence candidates: "
                    + ", ".join(sorted(self.missing_evidence_candidate_ids))
                ]
            return ["Submit an evidence-linked diagnosis before mutation."]
        if self.phase == WorkflowPhase.EDIT:
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
