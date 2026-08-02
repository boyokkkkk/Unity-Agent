from __future__ import annotations

import unittest
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

from game_agent.aci import AciConfig, UnityAciController, WorkflowPhase
from game_agent.aci.causal_facts import CausalClaimVerifier, build_causal_fact_matrix
from game_agent.aci.diagnosis import DiagnosisRecord
from game_agent.context import ContextAssembler, ContextConfig, ProjectContextStore
from game_agent.project_graph.schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph


def causal_graph() -> ProjectGraph:
    graph = ProjectGraph(metadata={"project_revision": "revision-1"})
    nodes = (
        Node("game-input", NodeKind.CLASS, "GameInput", "Assets/Scripts/GameInput.cs"),
        Node("manager", NodeKind.MONO_BEHAVIOUR, "KitchenGameManager", "Assets/Scripts/KitchenGameManager.cs"),
        Node("ui", NodeKind.MONO_BEHAVIOUR, "TutorialUI", "Assets/Scripts/UI/TutorialUI.cs"),
        Node("input-event", NodeKind.FIELD, "OnInteractAction", "Assets/Scripts/GameInput.cs", {
            "declaring_type": "GameInput", "is_event": True, "line": 10,
        }),
        Node("state-event", NodeKind.FIELD, "OnStateChanged", "Assets/Scripts/KitchenGameManager.cs", {
            "declaring_type": "KitchenGameManager", "is_event": True, "line": 12,
        }),
        Node("state", NodeKind.FIELD, "state", "Assets/Scripts/KitchenGameManager.cs", {
            "declaring_type": "KitchenGameManager", "line": 24,
        }),
        Node("interaction", NodeKind.METHOD, "GameInput_OnInteraction", "Assets/Scripts/KitchenGameManager.cs", {
            "declaring_type": "KitchenGameManager", "line": 42,
        }),
        Node("update", NodeKind.METHOD, "UpdateGamePlayingState", "Assets/Scripts/KitchenGameManager.cs", {
            "declaring_type": "KitchenGameManager", "line": 52,
        }),
        Node("observer", NodeKind.METHOD, "KitchenGameManager_OnStateChanged", "Assets/Scripts/UI/TutorialUI.cs", {
            "declaring_type": "TutorialUI", "line": 27,
        }),
        Node("hide", NodeKind.METHOD, "Hide", "Assets/Scripts/UI/TutorialUI.cs", {
            "declaring_type": "TutorialUI", "line": 61,
        }),
    )
    for node in nodes:
        graph.add_node(node)
    graph.add_edge(Edge("interaction", "input-event", EdgeKind.SUBSCRIBES_TO))
    graph.add_edge(Edge("interaction", "state", EdgeKind.WRITES_STATE, {
        "expression": "state = State.CountdownToStart",
    }))
    graph.add_edge(Edge("update", "state-event", EdgeKind.PUBLISHES_EVENT, {
        "expression": "OnStateChanged?.Invoke(this, EventArgs.Empty)",
    }))
    graph.add_edge(Edge("observer", "state-event", EdgeKind.SUBSCRIBES_TO))
    graph.add_edge(Edge("observer", "hide", EdgeKind.CALLS))
    return graph


class CausalFactMatrixTest(unittest.TestCase):
    def setUp(self):
        self.graph = causal_graph()
        self.matrix = build_causal_fact_matrix(
            self.graph,
            paths=(
                "Assets/Scripts/GameInput.cs",
                "Assets/Scripts/KitchenGameManager.cs",
                "Assets/Scripts/UI/TutorialUI.cs",
            ),
        )

    def test_roslyn_graph_generates_all_six_causal_slots(self):
        slots = self.matrix.public_dict()["slots"]

        self.assertEqual("present", slots["event_declaration"]["status"])
        self.assertEqual("present", slots["trigger_subscription"]["status"])
        self.assertEqual("present", slots["state_write"]["status"])
        self.assertEqual("absent", slots["event_publication"]["status"])
        self.assertEqual("present", slots["observer_subscription"]["status"])
        self.assertEqual("present", slots["observer_effect"]["status"])

    def test_absent_claim_requires_matching_controller_negative_proof(self):
        fact = next(
            item for item in self.matrix.facts
            if item.slot == "event_publication" and item.polarity == "absent"
        )
        claim = SimpleNamespace(
            subject=fact.subject,
            predicate=fact.predicate,
            object=fact.object,
            polarity=fact.polarity,
            fact_ids=[fact.fact_id],
            negative_evidence=SimpleNamespace(**fact.public_dict()["negative_evidence"]),
        )

        self.assertEqual([], CausalClaimVerifier(self.graph, self.matrix).verify(claim, claim_index=1))
        self.assertEqual("state = State.CountdownToStart", fact.ast_anchor)
        self.assertEqual(
            "OnStateChanged?.Invoke(this, EventArgs.Empty)",
            fact.repair_exemplar,
        )

        claim.negative_evidence.observed_matches = 1
        gaps = CausalClaimVerifier(self.graph, self.matrix).verify(claim, claim_index=1)
        self.assertIn("negative evidence does not match", " ".join(gaps))

    def test_symbol_existence_and_contradiction_gates_reject_hallucinations(self):
        subscription = next(
            item for item in self.matrix.facts
            if item.slot == "observer_subscription"
        )
        hallucinated_symbol = SimpleNamespace(
            subject="TutorialUI.MissingHandler",
            predicate="SUBSCRIBES_TO",
            object=subscription.object,
            polarity="present",
            fact_ids=[subscription.fact_id],
            negative_evidence=None,
        )
        gaps = CausalClaimVerifier(self.graph, self.matrix).verify(
            hallucinated_symbol, claim_index=1
        )
        self.assertIn("does not exist in the symbol table", " ".join(gaps))

        contradicted = SimpleNamespace(
            subject=subscription.subject,
            predicate=subscription.predicate,
            object=subscription.object,
            polarity="absent",
            fact_ids=[subscription.fact_id],
            negative_evidence=None,
        )
        gaps = CausalClaimVerifier(self.graph, self.matrix).verify(contradicted, claim_index=2)
        self.assertIn("relation is present", " ".join(gaps))


class AstAnchoredPatchTest(unittest.TestCase):
    def test_controller_fills_noncausal_claim_prose_and_root_evidence(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets/Scripts/UI/OptionUI.cs"
            source.parent.mkdir(parents=True)
            source.write_text("class OptionUI {}\n", encoding="utf-8")
            graph = ProjectGraph(project_path=str(project), metadata={"project_revision": "revision-1"})
            graph.add_node(Node("option", NodeKind.CSHARP_FILE, "OptionUI", "Assets/Scripts/UI/OptionUI.cs"))
            context = ContextAssembler(
                ContextConfig(auto_locate=False),
                project_root=project,
                project_store=ProjectContextStore.from_graph(graph, project_root=project),
            )
            context.reset("The sound-effects button does nothing.", task_id="ordinary-claim")
            controller = UnityAciController(
                context, project_root=project, config=AciConfig(workflow_enabled=True)
            )
            controller.workflow.frontier.reset()
            controller.workflow.frontier.add_rows([{
                "id": "option", "kind": "CSHARP_FILE",
                "path": "Assets/Scripts/UI/OptionUI.cs", "name": "OptionUI", "score": 1.0,
            }])
            evidence_id = context.record_verified_fact(
                "OptionUI source has no sound-effects click listener.",
                sources=["source:Assets/Scripts/UI/OptionUI.cs"], node_ids=["option"],
            )

            normalized = controller._normalize_causal_claim_arguments({
                "root_targets": ["C1"],
                "causal_chain": [{
                    "subject": "OptionUI.soundEffectsButton",
                    "predicate": "LACKS",
                    "object": "click listener",
                    "polarity": "absent",
                }],
            })

            claim = normalized["causal_chain"][0]
            self.assertIn("OptionUI.soundEffectsButton", claim["statement"])
            self.assertEqual([evidence_id], claim["evidence_ids"])

    def test_controller_derives_redundant_claim_fields_from_fact_id(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets/Scripts/KitchenGameManager.cs"
            source.parent.mkdir(parents=True)
            source.write_text("class KitchenGameManager {}\n", encoding="utf-8")
            graph = causal_graph()
            context = ContextAssembler(
                ContextConfig(auto_locate=False),
                project_root=project,
                project_store=ProjectContextStore.from_graph(graph, project_root=project),
            )
            context.reset("Fix missing state event publication", task_id="claim-normalization")
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(workflow_enabled=True, require_structured_causal_claims=True),
            )
            controller.workflow.frontier.reset()
            controller.workflow.frontier.add_rows([{
                # File-level candidate grouping may retain a representative method
                # other than the AST method named by the causal fact.
                "id": "update",
                "kind": "METHOD",
                "path": "Assets/Scripts/KitchenGameManager.cs",
                "name": "UpdateGamePlayingState",
                "score": 1.0,
            }])
            evidence_id = context.record_verified_fact(
                "Read KitchenGameManager source.",
                sources=["source:Assets/Scripts/KitchenGameManager.cs"],
                node_ids=["interaction"],
            )
            missing = next(
                fact for fact in build_causal_fact_matrix(graph, node_ids=["interaction"]).facts
                if fact.slot == "event_publication" and fact.polarity == "absent"
            )

            normalized = controller._normalize_causal_claim_arguments({
                "causal_chain": [{
                    "subject": missing.subject,
                    "predicate": missing.predicate,
                    "object": missing.object,
                    "polarity": missing.polarity,
                    "fact_ids": [missing.fact_id],
                }],
            })

            claim = normalized["causal_chain"][0]
            self.assertIn(missing.predicate, claim["statement"])
            self.assertEqual([evidence_id], claim["evidence_ids"])
            self.assertEqual(
                missing.negative_evidence.graph_revision,
                claim["negative_evidence"]["graph_revision"],
            )

    def test_diagnosis_and_patch_state_are_separate(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets/Scripts/KitchenGameManager.cs"
            source.parent.mkdir(parents=True)
            source.write_text(
                "class KitchenGameManager {\n"
                "    void GameInput_OnInteraction() {\n"
                "        state = State.CountdownToStart;\n"
                "    }\n"
                "}\n",
                encoding="utf-8",
            )
            graph = causal_graph()
            store = ProjectContextStore.from_graph(graph, project_root=project)
            context = ContextAssembler(
                ContextConfig(auto_locate=False),
                project_root=project,
                project_store=store,
            )
            context.reset("Fix missing state event publication", task_id="ast-patch")
            controller = UnityAciController(
                context,
                project_root=project,
                artifact_root=project / "artifacts",
                config=AciConfig(
                    workflow_enabled=True,
                    require_structured_causal_claims=True,
                ),
            )
            controller.workflow.frontier.reset()
            controller.workflow.frontier.add_rows([{
                "id": "interaction",
                "kind": "METHOD",
                "path": "Assets/Scripts/KitchenGameManager.cs",
                "name": "GameInput_OnInteraction",
                "score": 1.0,
            }])
            candidate = controller.workflow.frontier.candidates()[0]
            evidence = context.record_verified_fact(
                "Read the interaction state transition source.",
                sources=["source:Assets/Scripts/KitchenGameManager.cs"],
                node_ids=["interaction"],
            )
            diagnosis = DiagnosisRecord.from_arguments(
                {
                    "symptom": "State changes without notifying observers.",
                    "root_targets": [candidate.candidate_id],
                    "causal_chain": [],
                    "validation_plan": ["compile"],
                    "remaining_uncertainty": [],
                },
                version=1,
                repository_revision="revision-1",
                status="accepted",
            )
            controller.workflow.accept_diagnosis(
                diagnosis,
                authorized_targets={"update"},
                authorized_paths={"Assets/Scripts/KitchenGameManager.cs"},
                prepare_edit=True,
            )
            matrix = build_causal_fact_matrix(graph, node_ids=["update"])
            missing = next(
                fact for fact in matrix.facts
                if fact.slot == "event_publication" and fact.polarity == "absent"
            )

            prepared = controller.execute({
                "tool": "patch_prepare",
                "arguments": {
                    "target": candidate.candidate_id,
                    "causal_fact_id": missing.fact_id,
                    "operation": "ast_insert_after",
                    "evidence_id": evidence,
                    "use_repair_exemplar": True,
                },
            })

            self.assertEqual(0, prepared["returncode"])
            payload = prepared["extra"]["structured"]
            self.assertEqual(WorkflowPhase.EDIT, controller.workflow.phase)
            self.assertEqual("accepted", controller.workflow.diagnosis.status)
            self.assertEqual("prepared", controller.workflow.patch_status)
            self.assertEqual(
                "patch_prepared",
                controller.workflow.progress.events[-1].event_type.value,
            )
            self.assertEqual({"patch_apply", "diagnosis_revise", "artifact_read", "code_file_read"}, set(
                controller.tool_exposure().tool_names
            ))
            self.assertIn(
                "OnStateChanged?.Invoke(this, EventArgs.Empty);",
                payload["mutation_preview"]["new_text"],
            )
            self.assertEqual(
                controller.workflow.prepared_mutations[0].new_text,
                payload["mutation_preview"]["new_text"],
            )
            self.assertEqual(
                "diagnosis_locked",
                payload["workflow_state"]["causal_fact_matrix"]["status"],
            )
            self.assertIn("selected_facts", payload["workflow_state"]["causal_fact_matrix"])
            self.assertEqual([], payload["workflow_state"]["prepared_mutations"])

            applied = controller.execute({
                "tool": "patch_apply",
                "arguments": {"patch_token": payload["patch_token"]},
            })
            self.assertEqual(0, applied["returncode"])
            self.assertIn("OnStateChanged?.Invoke", source.read_text(encoding="utf-8"))
            recovery = controller._recover_compile_failure(
                "unity_recompile",
                {
                    "returncode": -2,
                    "exception_info": "CS0103: EventArgs does not exist",
                    "extra": {
                        "structured": {
                            "status": "failed",
                            "diagnostics": [{
                                "severity": "error",
                                "message": "CS0103: EventArgs does not exist",
                            }],
                        },
                    },
                },
            )
            self.assertEqual("restored", recovery["status"])
            self.assertNotIn("OnStateChanged?.Invoke", source.read_text(encoding="utf-8"))
            self.assertEqual(WorkflowPhase.PREPARE_EDIT, controller.workflow.phase)
            self.assertEqual("accepted", controller.workflow.diagnosis.status)
            self.assertEqual("compile_rejected", controller.workflow.patch_status)
            self.assertEqual(1, controller.workflow.compile_repair_attempts)


if __name__ == "__main__":
    unittest.main()
