from __future__ import annotations

import os
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from game_agent.aci import AciConfig, UnityAciController, WorkflowPhase
from game_agent.aci.candidate import CandidateFrontier
from game_agent.context import ContextAssembler, ContextConfig, ProjectContextStore
from game_agent.framework.agents.default import DefaultAgent
from game_agent.framework.exceptions import Submitted
from tests.test_aci import aci_graph


class WorkflowControllerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TEMP"))
        self.project = Path(self.temporary.name)
        self.artifacts = self.project / "artifacts"
        self.artifacts.mkdir()
        store = ProjectContextStore.from_graph(
            aci_graph(self.project),
            project_root=self.project,
        )
        self.context = ContextAssembler(
            ContextConfig(auto_locate=False, max_recent_messages=1),
            project_root=self.project,
            project_store=store,
        )
        self.context.reset("Fix interaction countdown state", task_id="workflow")
        self.controller = UnityAciController(
            self.context,
            project_root=self.project,
            artifact_root=self.artifacts,
            config=AciConfig(
                workflow_enabled=True,
                global_search_limit=2,
                graph_expansion_limit=3,
                candidate_frontier_size=5,
                mutation_required=True,
            ),
        )
        self.controller.reset()
        self._submit_plan(self.controller)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_frontier_collapses_csharp_file_type_and_method_to_one_candidate(self):
        frontier = CandidateFrontier(max_size=5)
        frontier.add_rows([
            {"id": "file", "kind": "CSHARP_FILE", "path": "Assets/Scripts/State.cs", "name": "State.cs"},
            {"id": "type", "kind": "CLASS", "path": "Assets/Scripts/State.cs", "name": "State"},
            {"id": "method", "kind": "METHOD", "path": "Assets/Scripts/State.cs", "name": "Transition"},
        ])

        self.assertEqual(1, len(frontier))
        self.assertEqual("METHOD", frontier.candidates()[0].entity_type)
        self.assertEqual("Transition", frontier.candidates()[0].symbol)

    def test_causal_evidence_gate_requires_input_controller_and_ui_reads(self):
        workflow = self.controller.workflow
        workflow.required_causal_roles = {"event_source", "controller", "ui"}
        workflow.frontier.reset()
        workflow.frontier.add_rows([
            {"id": "input", "kind": "CLASS", "path": "Assets/GameInput.cs", "name": "GameInput", "score": 1.0},
            {"id": "manager", "kind": "CLASS", "path": "Assets/KitchenGameManager.cs", "name": "KitchenGameManager", "score": 0.9},
            {"id": "ui", "kind": "CLASS", "path": "Assets/TutorialUI.cs", "name": "TutorialUI", "score": 0.8},
        ])
        workflow.phase = WorkflowPhase.INSPECT
        by_role = {candidate.role: candidate for candidate in workflow.frontier.candidates()}

        workflow.observe_candidate_read(by_role["event_source"].candidate_id, level="full", evidence_ids=["E1"])
        self.assertEqual(WorkflowPhase.INSPECT, workflow.phase)
        workflow.observe_candidate_read(by_role["controller"].candidate_id, level="full", evidence_ids=["E2"])
        self.assertEqual(WorkflowPhase.INSPECT, workflow.phase)
        self.assertIn("ui", " ".join(workflow.required_next_actions()))
        workflow.observe_candidate_read(by_role["ui"].candidate_id, level="full", evidence_ids=["E3"])

        self.assertEqual(WorkflowPhase.DIAGNOSE, workflow.phase)
        self.assertEqual(set(), workflow.missing_causal_roles())

    def test_frontier_retains_causal_roles_when_higher_scored_noise_arrives(self):
        frontier = CandidateFrontier(
            max_size=3, retained_roles={"event_source", "controller", "ui"}
        )
        frontier.add_rows([
            {"id": "input", "kind": "CLASS", "path": "Assets/GameInput.cs", "name": "GameInput", "score": 0.3},
            {"id": "manager", "kind": "CLASS", "path": "Assets/KitchenGameManager.cs", "name": "KitchenGameManager", "score": 0.2},
            {"id": "ui", "kind": "CLASS", "path": "Assets/TutorialUI.cs", "name": "TutorialUI", "score": 0.1},
            {"id": "noise", "kind": "CLASS", "path": "Assets/StoveCounter.cs", "name": "StoveCounter", "score": 1.0},
        ])

        self.assertEqual(
            {"event_source", "controller", "ui"},
            {candidate.role for candidate in frontier.candidates()},
        )

    @staticmethod
    def _submit_plan(controller):
        output = controller.execute({
            "tool": "task_plan_submit",
            "arguments": {
                "objective": "Fix the interaction countdown state.",
                "hypotheses": ["The state transition implementation is incorrect."],
                "required_evidence": ["Read the state controller implementation."],
                "success_criteria": ["The project compiles and Unity tests pass."],
                "validation_plan": ["compile", "editmode", "playmode"],
            },
        })
        if output["returncode"] != 0:
            raise AssertionError(output)
        return output

    def test_disobedient_model_cannot_bypass_search_budget_with_new_keywords(self):
        first = self.controller.execute({
            "tool": "unity_asset_search",
            "arguments": {"query": "countdown"},
        })
        second = self.controller.execute({
            "tool": "code_symbol_search",
            "arguments": {"query": "KitchenManager"},
        })
        third = self.controller.execute({
            "tool": "unity_object_search",
            "arguments": {"query": "interaction"},
        })

        self.assertEqual(0, first["returncode"])
        self.assertEqual(0, second["returncode"])
        self.assertNotEqual(0, third["returncode"])
        self.assertEqual("workflow_phase_or_budget", third["extra"]["guard"])
        self.assertEqual(2, self.controller.workflow.search_budget.global_used)
        self.assertEqual(WorkflowPhase.INSPECT, self.controller.workflow.phase)
        exposed = set(self.controller.tool_exposure().tool_names)
        self.assertIn("candidate_read", exposed)
        self.assertNotIn("unity_asset_search", exposed)
        self.assertNotIn("code_symbol_search", exposed)

    def test_candidate_read_resolves_private_node_without_model_node_id(self):
        self.controller.execute({
            "tool": "unity_asset_search",
            "arguments": {"query": "countdown"},
        })
        self.controller.execute({
            "tool": "code_symbol_search",
            "arguments": {"query": "KitchenManager"},
        })
        candidate = next(
            item for item in self.controller.workflow.frontier.public_candidates()
            if item["path"] == "Assets/Scripts/KitchenManager.cs"
        )
        action = {
            "tool": "candidate_read",
            "arguments": {"candidate_id": candidate["candidate_id"], "view": "symbol"},
        }
        output = self.controller.execute(action)
        self.context.record_tool_transition([action], [output], [])

        self.assertEqual(0, output["returncode"])
        self.assertEqual(
            "Assets/Scripts/KitchenManager.cs",
            output["extra"]["resolved_entity"]["path"],
        )
        self.assertTrue(output["extra"]["resolved_entity"]["node_id"])
        self.assertEqual(WorkflowPhase.DIAGNOSE, self.controller.workflow.phase)
        refreshed = self.controller.workflow.frontier.get(candidate["candidate_id"])
        self.assertEqual("symbol", refreshed.read_level)
        self.assertTrue(refreshed.evidence_ids)
        self.assertTrue(self.context.evidence.verified())
        self.assertIn("candidate_read", self.controller.tool_exposure().tool_names)
        self.assertIn("diagnosis_submit", self.controller.tool_exposure().tool_names)

        progress_version = self.controller.semantic_progress_version()
        repeated = self.controller.execute(action)
        self.assertEqual(-2, repeated["returncode"])
        self.assertEqual("workflow_phase_or_budget", repeated["extra"]["guard"])
        self.assertIn("already read", repeated["exception_info"].casefold())
        self.assertEqual(progress_version, self.controller.semantic_progress_version())

    def _read_implementation_candidate(self):
        self.controller.execute({
            "tool": "unity_asset_search",
            "arguments": {"query": "countdown"},
        })
        self.controller.execute({
            "tool": "code_symbol_search",
            "arguments": {"query": "KitchenManager"},
        })
        candidate = next(
            item for item in self.controller.workflow.frontier.public_candidates()
            if item["path"] == "Assets/Scripts/KitchenManager.cs"
        )
        output = self.controller.execute({
            "tool": "candidate_read",
            "arguments": {"candidate_id": candidate["candidate_id"], "view": "symbol"},
        })
        refreshed = self.controller.workflow.frontier.get(candidate["candidate_id"])
        return refreshed, output

    @staticmethod
    def _diagnosis_arguments(candidate_id, evidence_id):
        return {
            "symptom": "Countdown state does not advance after interaction.",
            "root_targets": [candidate_id],
            "causal_chain": [{
                "statement": "The inspected implementation contains the faulty countdown transition.",
                "evidence_ids": [evidence_id],
            }],
            "proposed_mutations": [{
                "target": candidate_id,
                "operation": "Correct the countdown transition implementation.",
                "evidence_id": evidence_id,
                "old_text": "ShowCountdown() {}",
                "new_text": "ShowCountdown() { }",
            }],
            "validation_plan": ["compile", "editmode", "playmode"],
            "remaining_uncertainty": [],
        }

    def test_diagnosis_requires_real_current_revision_evidence_and_preserves_versions(self):
        candidate, _ = self._read_implementation_candidate()
        bad = self._diagnosis_arguments(candidate.candidate_id, "evidence:missing")

        rejected = self.controller.execute({"tool": "diagnosis_submit", "arguments": bad})

        self.assertEqual(-2, rejected["returncode"])
        self.assertEqual("diagnosis_incomplete", rejected["extra"]["guard"])
        self.assertEqual(WorkflowPhase.DIAGNOSE, self.controller.workflow.phase)
        self.assertEqual(1, len(self.controller.workflow.diagnosis_history))
        self.assertIn("does not exist", " ".join(self.controller.workflow.diagnosis.gaps))

        good = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        evidence = self.context.evidence.items[candidate.evidence_ids[0]]
        evidence.repository_revision = "stale-revision"
        stale = self.controller.execute({"tool": "diagnosis_revise", "arguments": good})
        self.assertEqual(-2, stale["returncode"])
        self.assertIn("different repository revision", " ".join(self.controller.workflow.diagnosis.gaps))

        evidence.repository_revision = self.context.project_store.version.project_revision
        accepted = self.controller.execute({"tool": "diagnosis_revise", "arguments": good})

        self.assertEqual(0, accepted["returncode"])
        self.assertEqual(WorkflowPhase.EDIT, self.controller.workflow.phase)
        edit_tools = set(self.controller.tool_exposure().tool_names)
        self.assertEqual(
            {"unity_script_patch", "diagnosis_revise", "artifact_read", "code_file_read"},
            edit_tools,
        )
        self.assertEqual(3, len(self.controller.workflow.diagnosis_history))
        self.assertEqual(["rejected", "rejected", "accepted"], [
            item.status for item in self.controller.workflow.diagnosis_history
        ])
        self.assertIn(candidate.node_id, self.controller.workflow.authorized_targets)
        event_types = [event.event_type.value for event in self.controller.workflow.progress.events]
        self.assertIn("implementation_read", event_types)
        self.assertIn("diagnosis_accepted", event_types)

    def test_rejected_semantic_uncertainty_returns_to_inspect_for_recovery(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        diagnosis["remaining_uncertainty"] = [
            "Whether the state manager emits the transition event"
        ]

        rejected = self.controller.execute({
            "tool": "diagnosis_submit",
            "arguments": diagnosis,
        })

        self.assertEqual(-2, rejected["returncode"])
        self.assertEqual(WorkflowPhase.INSPECT, self.controller.workflow.phase)
        self.assertFalse(self.controller.workflow.missing_evidence_candidate_ids)
        exposed = set(self.controller.tool_exposure().tool_names)
        self.assertIn("candidate_read", exposed)
        self.assertIn("code_find_references", exposed)
        self.assertNotIn("global_search", exposed)
        self.assertIn("Read one candidate", " ".join(
            self.controller.workflow.required_next_actions()
        ))

    def test_diagnosis_rejects_invented_script_location_before_edit(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        diagnosis["proposed_mutations"][0].update({
            "operation": "Modify the imagined StartState.OnUpdate method.",
            "old_text": "public override void OnUpdate() { }",
            "new_text": "public override void OnUpdate() { StartCountdown(); }",
        })

        rejected = self.controller.execute({
            "tool": "diagnosis_submit", "arguments": diagnosis,
        })

        self.assertEqual(-2, rejected["returncode"])
        self.assertEqual(WorkflowPhase.INSPECT, self.controller.workflow.phase)
        self.assertFalse(self.controller.workflow.submission.diagnosis_accepted)
        self.assertIn(
            "old_text must occur exactly once",
            " ".join(self.controller.workflow.diagnosis.gaps),
        )
        exposed = set(self.controller.tool_exposure().tool_names)
        self.assertIn("code_file_read", exposed)
        self.assertIn("artifact_read", exposed)
        self.assertIn("diagnosis_revise", exposed)
        self.assertIn(
            "local old_text/new_text",
            " ".join(self.controller.workflow.required_next_actions()),
        )
        self.assertRegex(
            " ".join(self.controller.workflow.required_next_actions()),
            r"artifact_read|code_file_read",
        )
        recovery = self.controller.handle_no_progress()
        self.assertFalse(recovery.terminate)
        self.assertEqual(WorkflowPhase.INSPECT, self.controller.workflow.phase)

    def test_diagnosis_rejects_structurally_invalid_type_declaration_patch(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        diagnosis["proposed_mutations"][0].update({
            "operation": "Insert replacement behavior at the class declaration.",
            "old_text": "class KitchenManager",
            "new_text": (
                "class KitchenManager\n{\n"
                "    private void Start() { ShowCountdown(); }\n"
            ),
        })

        rejected = self.controller.execute({
            "tool": "diagnosis_submit", "arguments": diagnosis,
        })

        self.assertEqual(-2, rejected["returncode"])
        gaps = " ".join(self.controller.workflow.diagnosis.gaps)
        self.assertIn("type declaration, not a local edit site", gaps)
        self.assertIn("braces unbalanced", gaps)

    def test_csharp_preflight_rejects_unverified_enum_members(self):
        source = "private enum State { Waiting, Countdown } void Tick() { state = State.Waiting; }"
        old = "state = State.Waiting;"
        new = "state = State.Tutorial;"

        gaps = self.controller._csharp_patch_preflight(
            source, old, new, source.replace(old, new, 1),
        )

        self.assertIn("State.Tutorial", " ".join(gaps))

    def test_mutation_target_must_be_authorized_by_accepted_diagnosis(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        accepted = self.controller.execute({"tool": "diagnosis_submit", "arguments": diagnosis})
        self.assertEqual(0, accepted["returncode"])

        blocked = self.controller.execute({
            "tool": "unity_script_patch",
            "arguments": {
                "path": "Assets/Scripts/KitchenManager.cs",
                "old_text": "ShowCountdown",
                "new_text": "HideCountdown",
                "expected_sha256": "0" * 64,
                "evidence_node_ids": ["unauthorized-node"],
            },
        })

        self.assertEqual(-2, blocked["returncode"])
        self.assertEqual("mutation_target_unauthorized", blocked["extra"]["guard"])

        deviated = self.controller.execute({
            "tool": "unity_script_patch",
            "arguments": {
                "path": "Assets/Scripts/KitchenManager.cs",
                "old_text": "StartCountdown()",
                "new_text": "BeginCountdown()",
                "expected_sha256": "0" * 64,
                "evidence_node_ids": [candidate.node_id],
            },
        })
        self.assertEqual(-2, deviated["returncode"])
        self.assertEqual("mutation_deviates_from_diagnosis", deviated["extra"]["guard"])

        source = self.project / "Assets" / "Scripts" / "KitchenManager.cs"
        allowed = self.controller.execute({
            "tool": "unity_script_patch",
            "arguments": {
                "path": "Assets/Scripts/KitchenManager.cs",
                "old_text": "ShowCountdown() {}",
                "new_text": "ShowCountdown() { }",
                "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "evidence_node_ids": [candidate.node_id],
            },
        })

        self.assertEqual(0, allowed["returncode"])
        self.assertEqual(WorkflowPhase.VALIDATE, self.controller.workflow.phase)
        self.assertEqual(
            "mutation_applied",
            self.controller.workflow.progress.events[-1].event_type.value,
        )
        self.assertEqual(
            {"code_diagnostics", "artifact_read"},
            set(self.controller.tool_exposure().tool_names),
        )
        self.controller._consume_query(
            "code_diagnostics",
            {
                "returncode": 0,
                "extra": {
                    "structured": {
                        "status": "partial",
                        "diagnostics": [],
                        "compiler_diagnostics_available": False,
                    }
                },
            },
        )
        self.assertTrue(self.controller.pending.diagnostics_complete)
        self.assertEqual(
            {"unity_recompile"},
            set(self.controller.tool_exposure().tool_names),
        )
        self.assertIn(
            "unity_recompile",
            " ".join(self.controller.protocol_state()["workflow"]["required_next_actions"]),
        )
        self.controller.pending.diagnostics_complete = True
        self.controller.pending.reload_complete = True
        self.controller.workflow.observe_diagnostics_passed()
        self.controller.workflow.observe_compile_passed()
        self.controller._consume_control(
            "unity_validate",
            {
                "returncode": 0,
                "extra": {"structured": {"status": "ok"}, "validation_modes": ["editmode"]},
            },
        )
        self.controller._consume_control(
            "unity_validate",
            {
                "returncode": 0,
                "extra": {"structured": {"status": "ok"}, "validation_modes": ["playmode"]},
            },
        )
        self.assertIsNone(self.controller.pending)
        self.assertEqual(WorkflowPhase.SUBMIT, self.controller.workflow.phase)
        self.assertTrue(self.controller.workflow.submission.final_review_passed)
        self.assertIsNotNone(self.controller.automatic_submission())

    def test_failed_mutation_forces_relocalization_and_exposes_recovery(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        self.assertEqual(0, self.controller.execute({
            "tool": "diagnosis_submit", "arguments": diagnosis,
        })["returncode"])

        source = self.project / "Assets" / "Scripts" / "KitchenManager.cs"
        source.write_text(
            source.read_text(encoding="utf-8").replace("ShowCountdown() {}", "ShowCountdown() { }"),
            encoding="utf-8",
        )
        failed = self.controller.execute({
            "tool": "unity_script_patch",
            "arguments": {
                "path": "Assets/Scripts/KitchenManager.cs",
                "old_text": "ShowCountdown() {}",
                "new_text": "ShowCountdown() { }",
                "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "evidence_node_ids": [candidate.node_id],
            },
        })

        self.assertNotEqual(0, failed["returncode"])
        self.assertEqual(WorkflowPhase.INSPECT, self.controller.workflow.phase)
        self.assertFalse(self.controller.workflow.submission.diagnosis_accepted)
        self.assertIn("diagnosis_revise", self.controller.workflow.stage_directive)
        self.assertEqual("mutation_failed", self.controller.workflow.progress.events[-1].event_type.value)
        recovery = failed["extra"]["workflow_recovery"]
        self.assertEqual("inspect", recovery["phase"])
        exposed = set(self.controller.tool_exposure().tool_names)
        self.assertIn("artifact_read", exposed)
        self.assertIn("code_file_read", exposed)
        self.assertIn("diagnosis_revise", exposed)

        reread = self.controller.execute({
            "tool": "code_file_read",
            "arguments": {"path": "Assets/Scripts/KitchenManager.cs"},
        })
        self.assertEqual(0, reread["returncode"])
        refreshed_evidence = next(
            item
            for item in reversed(self.context.evidence.verified())
            if candidate.node_id in item.node_ids
        )
        revised = self._diagnosis_arguments(candidate.candidate_id, refreshed_evidence.id)
        revised["proposed_mutations"][0].update({
            "old_text": "ShowCountdown() { }",
            "new_text": "ShowCountdown() { /* recovered */ }",
        })
        accepted = self.controller.execute({
            "tool": "diagnosis_revise", "arguments": revised,
        })
        self.assertEqual(0, accepted["returncode"])
        self.assertEqual(WorkflowPhase.EDIT, self.controller.workflow.phase)
        self.assertIsNone(self.controller.workflow.last_mutation_failure)

    def test_review_is_controller_owned_and_completes_full_submission_contract(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        self.assertEqual(0, self.controller.execute({
            "tool": "diagnosis_submit", "arguments": diagnosis,
        })["returncode"])
        contract = self.controller.workflow.submission
        contract.mutation_count = 1
        contract.changed_paths_authorized = True
        contract.diagnostics_passed = True
        contract.compile_passed = True
        contract.required_tests_passed = True
        contract.validation_complete = True
        self.controller.completed = [{
            "changed_paths": ["Assets/Scripts/KitchenManager.cs"],
            "completed_validation_modes": ["editmode", "playmode"],
        }]
        self.controller.workflow.phase = WorkflowPhase.REVIEW

        blocked = self.controller.guard_submission()
        self.assertEqual("review_required", blocked["extra"]["guard"])
        review = self.controller.execute({"tool": "workflow_review", "arguments": {}})

        self.assertEqual(0, review["returncode"])
        self.assertEqual("accepted", review["extra"]["structured"]["status"])
        self.assertEqual(WorkflowPhase.SUBMIT, self.controller.workflow.phase)
        self.assertEqual([], contract.unmet())
        self.assertIsNone(self.controller.guard_submission())
        self.assertIn("Controller verified", self.controller.automatic_submission())

    def test_review_rejects_actual_diff_outside_diagnosis(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        self.controller.execute({"tool": "diagnosis_submit", "arguments": diagnosis})
        contract = self.controller.workflow.submission
        contract.mutation_count = 1
        contract.changed_paths_authorized = True
        contract.diagnostics_passed = True
        contract.compile_passed = True
        contract.required_tests_passed = True
        contract.validation_complete = True
        self.controller.completed = [{
            "changed_paths": ["Assets/Scripts/Other.cs"],
            "completed_validation_modes": ["editmode", "playmode"],
        }]
        self.controller.workflow.phase = WorkflowPhase.REVIEW

        review = self.controller.execute({"tool": "workflow_review", "arguments": {}})

        self.assertEqual(-2, review["returncode"])
        self.assertEqual("review_failed", review["extra"]["guard"])
        self.assertIn("exceeds diagnosis", review["exception_info"])
        self.assertEqual(WorkflowPhase.EDIT, self.controller.workflow.phase)

    def test_agent_auto_submits_immediately_when_review_completes_contract(self):
        candidate, _ = self._read_implementation_candidate()
        diagnosis = self._diagnosis_arguments(candidate.candidate_id, candidate.evidence_ids[0])
        self.controller.execute({"tool": "diagnosis_submit", "arguments": diagnosis})
        contract = self.controller.workflow.submission
        contract.mutation_count = 1
        contract.changed_paths_authorized = True
        contract.diagnostics_passed = True
        contract.compile_passed = True
        contract.required_tests_passed = True
        contract.validation_complete = True
        self.controller.completed = [{
            "changed_paths": ["Assets/Scripts/KitchenManager.cs"],
            "completed_validation_modes": ["editmode", "playmode"],
        }]
        self.controller.workflow.phase = WorkflowPhase.REVIEW

        class AutoSubmitModel:
            config = SimpleNamespace(model_name="auto-submit-fixture")

            def set_available_tool_names(self, names):
                self.available_tool_names = tuple(names)

            def format_observation_messages(self, message, outputs, template_vars=None):
                return [{
                    "role": "tool",
                    "tool_call_id": action["tool_call_id"],
                    "content": output["output"],
                } for action, output in zip(message["extra"]["actions"], outputs)]

            def format_message(self, **kwargs):
                return kwargs

            def get_template_vars(self, **kwargs):
                return kwargs

        class AutoSubmitEnvironment:
            config = SimpleNamespace(cwd="", artifact_dir="")

            def finalize_output(self, output):
                return output

            def get_template_vars(self, **kwargs):
                return kwargs

        agent = DefaultAgent(
            AutoSubmitModel(),
            AutoSubmitEnvironment(),
            system_template="system",
            instance_template="{{ task }}",
            aci=self.controller.config,
            context_assembler=self.context,
            aci_controller=self.controller,
        )
        agent._configure_tool_exposure()
        with self.assertRaises(Submitted) as raised:
            agent.execute_actions({
                "role": "assistant",
                "content": "",
                "extra": {"actions": [{
                    "tool": "workflow_review",
                    "arguments": {},
                    "tool_call_id": "review-1",
                }]},
            })

        submission = raised.exception.messages[0]
        self.assertTrue(submission["extra"]["automatic_submission"])
        self.assertEqual("Submitted", submission["extra"]["exit_status"])

    def test_progress_ledger_ignores_novel_search_text_and_recovers_by_phase(self):
        class EmptySearchExecutor:
            calls = 0

            def execute(self, action):
                self.calls += 1
                query = action["arguments"]["query"]
                payload = {"status": "ok", "query": query, "results": []}
                return {
                    "output": json.dumps(payload),
                    "returncode": 0,
                    "exception_info": "",
                    "extra": {
                        "aci": True,
                        "structured": payload,
                        "evidence_claim": f"Search {query} returned no candidates.",
                        "evidence_sources": [f"search:{query}"],
                        "evidence_status": "observed",
                    },
                }

        class FixtureModel:
            config = SimpleNamespace(model_name="progress-fixture")

            def set_available_tool_names(self, tool_names):
                self.available_tool_names = tuple(tool_names)

            def format_message(self, **kwargs):
                return kwargs

            def format_observation_messages(self, message, outputs, template_vars=None):
                return [{
                    "role": "tool",
                    "content": output["output"],
                    "tool_call_id": action["tool_call_id"],
                } for action, output in zip(message["extra"]["actions"], outputs)]

            def get_template_vars(self, **kwargs):
                return kwargs

        class FixtureEnvironment:
            config = SimpleNamespace(cwd="", artifact_dir="")

            def finalize_output(self, output):
                return output

            def get_template_vars(self, **kwargs):
                return kwargs

        controller = UnityAciController(
            self.context,
            project_root=self.project,
            config=AciConfig(workflow_enabled=True, global_search_limit=5),
            query_executor=EmptySearchExecutor(),
        )
        controller.reset()
        self._submit_plan(controller)
        agent = DefaultAgent(
            FixtureModel(),
            FixtureEnvironment(),
            system_template="system",
            instance_template="{{ task }}",
            max_no_progress_rounds=2,
            aci=controller.config,
            context_assembler=self.context,
            aci_controller=controller,
        )
        agent._configure_tool_exposure()
        for index, query in enumerate(("alpha", "beta"), start=1):
            agent.execute_actions({
                "role": "assistant",
                "content": "",
                "extra": {"actions": [{
                    "tool": "unity_asset_search",
                    "arguments": {"query": query},
                    "tool_call_id": f"search-{index}",
                }]},
            })

        self.assertEqual(0, controller.semantic_progress_version())
        self.assertEqual(WorkflowPhase.INSPECT, controller.workflow.phase)
        self.assertEqual(0, agent.no_progress_rounds)
        self.assertTrue(any(
            message.get("extra", {}).get("workflow_no_progress_recovery")
            for message in agent.messages
        ))

    def test_no_progress_policy_is_phase_specific(self):
        workflow = self.controller.workflow

        workflow.phase = WorkflowPhase.INSPECT
        inspect = workflow.handle_no_progress()
        self.assertFalse(inspect.terminate)
        self.assertEqual(WorkflowPhase.DIAGNOSE, inspect.phase_after)

        diagnose_first = workflow.handle_no_progress()
        diagnose_second = workflow.handle_no_progress()
        self.assertFalse(diagnose_first.terminate)
        self.assertTrue(diagnose_second.terminate)

        workflow.phase = WorkflowPhase.EDIT
        edit = workflow.handle_no_progress()
        self.assertFalse(edit.terminate)
        self.assertIn("diff", workflow.stage_directive)

        workflow.phase = WorkflowPhase.VALIDATE
        validate = workflow.handle_no_progress()
        self.assertTrue(validate.terminate)
        self.assertIn("last definite result", validate.message)

    def test_zero_mutation_submission_is_blocked(self):
        blocked = self.controller.guard_submission()

        self.assertIsNotNone(blocked)
        self.assertEqual("mutation_required", blocked["extra"]["guard"])
        self.assertEqual(WorkflowPhase.EXPLORE, self.controller.workflow.phase)

    def test_execution_layer_rejects_a_tool_hidden_by_current_phase(self):
        class ExposureModel:
            config = SimpleNamespace(model_name="exposure-fixture")

            def __init__(self):
                self.available_tool_names = ()

            def set_available_tool_names(self, tool_names):
                self.available_tool_names = tuple(tool_names)

        class RecordingEnvironment:
            def __init__(self, cwd):
                self.config = SimpleNamespace(cwd=str(cwd), artifact_dir="")
                self.actions = []

            def execute(self, action):
                self.actions.append(action)
                return {"output": "unexpected", "returncode": 0, "exception_info": ""}

        model = ExposureModel()
        environment = RecordingEnvironment(self.project)
        agent = DefaultAgent(
            model,
            environment,
            system_template="system",
            instance_template="{{ task }}",
            aci=self.controller.config,
            context_assembler=self.context,
            aci_controller=self.controller,
        )
        agent._configure_tool_exposure()

        output = agent._execute_action({"tool": "powershell", "command": "Set-Content bypass.txt x"})

        self.assertNotIn("powershell", model.available_tool_names)
        self.assertEqual(-2, output["returncode"])
        self.assertEqual("general_shell_forbidden", output["extra"]["guard"])
        self.assertEqual([], environment.actions)

    def test_workflow_capsule_survives_recent_history_trimming(self):
        self.controller.execute({
            "tool": "unity_asset_search",
            "arguments": {"query": "countdown"},
        })
        self.controller.execute({
            "tool": "code_symbol_search",
            "arguments": {"query": "KitchenManager"},
        })
        self.context.set_control_state(self.controller.protocol_state())
        messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "task"}]
        messages.extend(
            {"role": "assistant", "content": f"old message {index}"}
            for index in range(20)
        )

        assembled = self.context.assemble(
            messages,
            raw_input_tokens=10000,
            max_input_tokens=12000,
            budget={},
        )
        view = assembled[-1]["content"]
        self.assertIn("<workflow-state>", view)
        self.assertIn('"phase": "inspect"', view)
        self.assertIn('"candidate_frontier"', view)
        self.assertIn("candidate_read", view)
        self.assertNotIn("old message 0", view)
        self.assertEqual(1, view.count('"candidate_frontier"'))
        self.assertEqual(1, view.count('"submission_contract"'))


if __name__ == "__main__":
    unittest.main()
