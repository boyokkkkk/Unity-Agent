from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from game_agent.context import (
    ContextAssembler,
    ContextConfig,
    EvidenceLedger,
    EvidenceStatus,
    ProjectContextStore,
    TaskWorkingSet,
    WorkingSetEntry,
)
from game_agent.framework.agents.default import DefaultAgent
from game_agent.framework.environments.local import LocalEnvironment
from game_agent.project_graph.schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph
from game_agent.project_graph.retrieval import LocalizationResult


def context_graph(project: Path) -> ProjectGraph:
    source = project / "Assets" / "Scripts" / "KitchenManager.cs"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "class KitchenManager { void StartCountdown() { ShowCountdown(); } void ShowCountdown() {} }",
        encoding="utf-8",
    )
    graph = ProjectGraph(project_path=str(project), metadata={"project_revision": "revision-1"})
    for node in (
        Node("file", NodeKind.CSHARP_FILE, "KitchenManager.cs", "Assets/Scripts/KitchenManager.cs"),
        Node("type", NodeKind.MONO_BEHAVIOUR, "KitchenManager", "Assets/Scripts/KitchenManager.cs"),
        Node(
            "start",
            NodeKind.METHOD,
            "StartCountdown",
            "Assets/Scripts/KitchenManager.cs",
            {"line": 1},
        ),
        Node("show", NodeKind.METHOD, "ShowCountdown", "Assets/Scripts/KitchenManager.cs"),
        Node(
            "component",
            NodeKind.COMPONENT,
            "KitchenManager",
            "Assets/Scenes/Game.unity",
            {"code_symbol_id": "type", "script_path": "Assets/Scripts/KitchenManager.cs"},
        ),
        Node(
            "go",
            NodeKind.GAME_OBJECT,
            "CountdownCanvas",
            "Assets/Scenes/Game.unity",
            {"hierarchy_path": "UI/CountdownCanvas"},
        ),
    ):
        graph.add_node(node)
    graph.add_edge(Edge("start", "show", EdgeKind.CALLS))
    graph.add_edge(Edge("component", "go", EdgeKind.ATTACHED_TO))
    return graph


class ProjectContextStoreTest(unittest.TestCase):
    def test_causal_query_fusion_retains_input_controller_and_ui_before_limit(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph = ProjectGraph(project_path=str(project))
            paths = (
                "Assets/GameInput.cs",
                "Assets/KitchenGameManager.cs",
                "Assets/TutorialUI.cs",
                "Assets/CuttingCounter.cs",
            )
            for index, path in enumerate(paths):
                target = project / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Source {}", encoding="utf-8")
                graph.add_node(Node(f"n{index}", NodeKind.CSHARP_FILE, Path(path).stem, path))
            store = ProjectContextStore.from_graph(graph, project_root=project)
            calls = []

            def retrieve(query, *args, **kwargs):
                calls.append(query)
                if "input action" in query:
                    order = [0, 3, 1, 2]
                elif "state transition" in query:
                    order = [1, 3, 0, 2]
                elif "UI observer" in query:
                    order = [2, 3, 1, 0]
                else:
                    order = [3, 0, 1, 2]
                return LocalizationResult(
                    variant="A2", strategy="role_mmr",
                    files=[{"path": paths[i], "score": 1.0 - rank * 0.1} for rank, i in enumerate(order)],
                    game_objects=[], assets=[], ranked_nodes=[], dependency_paths=[],
                )

            store._retriever.retrieve = retrieve
            entries = store.locate(
                "causal", "Interaction input state event UI observer failure",
                limit=3, causal_query_decomposition=True, causal_role_retention=True,
            )

            self.assertGreaterEqual(len(calls), 4)
            self.assertEqual(
                {"GameInput", "KitchenGameManager", "TutorialUI"},
                {entry.name for entry in entries},
            )

    def test_locate_merges_and_scores_by_file_before_limit(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph = ProjectGraph(project_path=str(project))
            for path in ("Assets/A.cs", "Assets/B.cs"):
                target = project / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("class Source {}", encoding="utf-8")
            for node in (
                Node("file-a", NodeKind.CSHARP_FILE, "A.cs", "Assets/A.cs"),
                Node("method-a", NodeKind.METHOD, "A", "Assets/A.cs"),
                Node("file-b", NodeKind.CSHARP_FILE, "B.cs", "Assets/B.cs"),
                Node("method-b", NodeKind.METHOD, "B", "Assets/B.cs"),
            ):
                graph.add_node(node)
            store = ProjectContextStore.from_graph(graph, project_root=project)
            store._retriever.retrieve = lambda *args, **kwargs: LocalizationResult(
                variant="A2",
                strategy="role_mmr",
                files=[
                    {"path": "Assets/B.cs", "score": 0.9},
                    {"path": "Assets/A.cs", "score": 0.8},
                ],
                game_objects=[],
                assets=[],
                ranked_nodes=[
                    {"id": "method-a", "score": 0.99},
                    {"id": "file-a", "score": 0.98},
                    {"id": "method-b", "score": 0.5},
                ],
                dependency_paths=[],
            )

            entries = store.locate("task", "query", limit=2)

            self.assertEqual(["method-a", "method-b"], [entry.node_id for entry in entries])
            self.assertEqual([0.99, 0.9], [entry.relevance for entry in entries])
            self.assertEqual(2, len({entry.path for entry in entries}))

    def test_existing_working_set_keeps_the_strictest_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            store = ProjectContextStore.from_graph(context_graph(project), project_root=project)
            working_set = store.working_set("task", max_entries=2)
            for node in list(store.graph.nodes.values())[:3]:
                store.map_node_ids("task", [node.id])

            self.assertEqual(working_set.max_entries, 2)
            self.assertLessEqual(len(working_set.entries), 2)

    def test_immutable_project_knowledge_is_reused_across_tasks_and_stores(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph_path = project / "project-graph.json"
            context_graph(project).save(graph_path)

            first = ProjectContextStore.open(graph_path, project_root=project)
            second = ProjectContextStore.open(graph_path, project_root=project)
            first.locate("task-a", "KitchenManager StartCountdown", limit=4)
            first.locate("task-b", "CountdownCanvas", limit=4)

            self.assertIs(first.graph, second.graph)
            self.assertEqual(2, first.metrics()["tasks"])
            self.assertNotEqual(
                first.working_set("task-a").task_id,
                first.working_set("task-b").task_id,
            )
            self.assertEqual(first.version.graph_digest, second.version.graph_digest)

    def test_graph_is_paged_invalidated_and_remapped(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            state_path = project / "context-state.json"
            graph = context_graph(project)
            store = ProjectContextStore.from_graph(
                graph,
                project_root=project,
                state_path=state_path,
            )

            entries = store.locate("task-1", "KitchenManager StartCountdown CountdownCanvas", limit=6)
            self.assertTrue(entries)
            target = next(entry for entry in entries if entry.node_id == "start")

            first = store.materialize("task-1", target.node_id)
            second = store.materialize("task-1", target.node_id)

            self.assertEqual("StartCountdown", first["name"])
            self.assertEqual(1, first["source_range"]["start_line"])
            self.assertIn("StartCountdown", first["source_excerpt"][0]["text"])
            self.assertEqual(first, second)
            metrics = store.working_set("task-1").metrics()
            self.assertEqual(1, metrics["context_hits"])
            self.assertEqual(1, metrics["context_misses"])

            source = project / "Assets" / "Scripts" / "KitchenManager.cs"
            source.write_text(source.read_text(encoding="utf-8") + "\n// changed", encoding="utf-8")
            changed = store.detect_changes()

            self.assertIn("assets/scripts/kitchenmanager.cs", changed)
            self.assertIn("start", store.dirty_nodes)
            self.assertIsNone(store.materialize("task-1", "start"))
            self.assertTrue(state_path.is_file())

            refreshed = context_graph(project)
            refreshed.metadata["project_revision"] = "revision-2"
            result = store.refresh(refreshed)

            self.assertGreater(result["remapped"], 0)
            self.assertFalse(store.dirty_nodes)
            self.assertEqual("revision-2", store.version.project_revision)
            self.assertIsNotNone(store.materialize("task-1", "start"))

    def test_precision_counts_rejected_and_evidence_survives_detail_eviction(self):
        working_set = TaskWorkingSet("task")
        working_set.add(WorkingSetEntry("one", "METHOD", "One", "Assets/One.cs", detail={"body": "one"}))
        working_set.add(WorkingSetEntry("two", "METHOD", "Two", "Assets/Two.cs", detail={"body": "two"}))
        ledger = EvidenceLedger()
        evidence = ledger.add(
            "One is the verified root cause.",
            status=EvidenceStatus.SOURCE_VERIFIED,
            sources=["Assets/One.cs:10"],
            node_ids=["one"],
        )
        working_set.label("one", True, evidence_id=evidence.id)
        working_set.label("two", False)

        working_set.evict_details(keep=0)

        self.assertEqual(0.5, working_set.metrics()["working_set_precision"])
        self.assertIsNone(working_set.entries["one"].detail)
        self.assertEqual("One is the verified root cause.", ledger.verified()[0].claim)


class ContextAssemblerTest(unittest.TestCase):
    def test_virtual_context_surfaces_evidence_conditioned_control_state(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            context = ContextAssembler(
                ContextConfig(auto_locate=False),
                project_root=Path(directory),
            )
            context.reset("repair", task_id="control-state")
            context.set_control_state({
                "completed_actions": [],
                "disabled_actions": ["code_file_read:done"],
                "unresolved_slots": [{"id": "implementation_source", "status": "open"}],
                "admissible_action_signatures": ["code_symbol_search:next"],
            })

            assembled = context.assemble([
                {"role": "system", "content": "system"},
                {"role": "user", "content": "repair"},
            ])

            rendered = assembled[-1]["content"]
            payload = json.loads(rendered[rendered.index("{") : rendered.rindex("}") + 1])
            control = payload["evidence_conditioned_control"]
            self.assertEqual(
                "implementation_source",
                control["unresolved_slots"][0]["id"],
            )
            self.assertEqual(
                ["code_symbol_search:next"],
                control["admissible_action_signatures"],
            )

    def test_assembler_uses_structured_memory_and_externalized_tool_results(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            store = ProjectContextStore.from_graph(context_graph(project), project_root=project)
            assembler = ContextAssembler(
                ContextConfig(
                    auto_locate=False,
                    max_recent_tool_results=1,
                    max_candidate_details=3,
                    compression_trigger_ratio=0.5,
                ),
                project_root=project,
                project_store=store,
            )
            assembler.reset("Fix KitchenManager countdown", task_id="task")
            # File-level localization deliberately collapses code candidates;
            # map the separately judged scene object explicitly for this
            # evidence-precision assertion.
            store.map_node_ids("task", ["start", "go"])
            assembler.record_verified_fact(
                "StartCountdown calls ShowCountdown.",
                sources=["Assets/Scripts/KitchenManager.cs:1"],
                node_ids=["start"],
            )
            assembler.reject_hypothesis(
                "CountdownCanvas has no controlling script.",
                sources=["graph:component"],
                node_ids=["go"],
            )
            assembler.record_tool_transition(
                [{"command": "Get-Content Assets/Scripts/KitchenManager.cs"}],
                [{
                    "output": "old raw output that should be externalized",
                    "returncode": 0,
                    "extra": {"artifact_path": "tool-outputs/old.txt", "output_truncated": True},
                }],
                [{
                    "role": "tool",
                    "content": "old raw output that should be externalized",
                    "extra": {"artifact_path": "tool-outputs/old.txt", "output_truncated": True},
                }],
            )
            assembler.record_tool_transition(
                [{"command": "Get-Content Assets/Scripts/KitchenManager.cs"}],
                [{
                    "output": "latest compact result",
                    "returncode": 0,
                    "extra": {"artifact_path": "tool-outputs/latest.txt"},
                }],
                [{
                    "role": "tool",
                    "content": "latest compact result",
                    "extra": {"artifact_path": "tool-outputs/latest.txt"},
                }],
            )
            history = [
                {"role": "system", "content": "stable constraints"},
                {"role": "user", "content": "Fix KitchenManager countdown"},
                {"role": "tool", "content": "old raw output that should be externalized"},
            ]

            view = assembler.assemble(
                history,
                raw_input_tokens=800,
                max_input_tokens=1000,
                budget={"remaining_total_tokens": 5000},
            )

            self.assertEqual(2, len(view))
            self.assertEqual("stable constraints", view[0]["content"])
            self.assertNotIn("old raw output that should be externalized", view[1]["content"])
            self.assertIn("latest compact result", view[1]["content"])
            self.assertIn("StartCountdown calls ShowCountdown", view[1]["content"])
            self.assertIn("tool-outputs/old.txt", view[1]["content"])
            self.assertEqual(1, assembler.compression_count)
            self.assertEqual(0.5, assembler.working_set.metrics()["working_set_judged_precision"])
            current_plan = next(item for item in assembler.plan if item["phase"] == "evidence_verification")
            self.assertEqual("in_progress", current_plan["status"])

    def test_linear_agent_queries_virtual_view_but_retains_full_trajectory(self):
        class CapturingModel:
            config = {}

            def __init__(self):
                self.calls = []

            def estimate_input_tokens(self, messages):
                return len(json.dumps(messages, ensure_ascii=False))

            def query(self, messages, **kwargs):
                self.calls.append(messages)
                if len(self.calls) == 1:
                    return {
                        "role": "assistant",
                        "content": "",
                        "extra": {
                            "actions": [{
                                "tool": "powershell",
                                "command": "Write-Output first-observation",
                                "tool_call_id": "call-1",
                            }],
                            "prompt_tokens": 50,
                            "completion_tokens": 5,
                            "total_tokens": 55,
                        },
                    }
                return {
                    "role": "assistant",
                    "content": "",
                    "extra": {
                        "actions": [{
                            "tool": "submit",
                            "answer": "done",
                            "tool_call_id": "submit-1",
                        }],
                        "prompt_tokens": 50,
                        "completion_tokens": 5,
                        "total_tokens": 55,
                    },
                }

            def format_message(self, **kwargs):
                return kwargs

            def format_observation_messages(self, message, outputs, template_vars=None):
                return [
                    {
                        "role": "tool",
                        "content": output.get("output", ""),
                        "tool_call_id": action.get("tool_call_id", ""),
                        "extra": output.get("extra", {}),
                    }
                    for action, output in zip(message["extra"]["actions"], outputs)
                ]

            def get_template_vars(self, **kwargs):
                return {}

            def serialize(self):
                return {}

        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            model = CapturingModel()
            trajectory = Path(directory) / "trajectory.json"
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, artifact_dir=directory),
                system_template="stable system",
                instance_template="{{ task }}",
                output_path=trajectory,
                step_limit=4,
                context={"enabled": True, "max_recent_tool_results": 1},
            )

            result = agent.run("finish through virtual context")

            self.assertEqual("Submitted", result["exit_status"])
            self.assertEqual([2, 2], [len(messages) for messages in model.calls])
            self.assertTrue(all("virtual-project-context" in messages[1]["content"] for messages in model.calls))
            self.assertGreater(len(agent.messages), len(model.calls[-1]))
            saved = json.loads(trajectory.read_text(encoding="utf-8"))
            self.assertTrue(saved["context"]["enabled"])
            self.assertEqual(2, saved["context"]["metrics"]["context_builds"])


if __name__ == "__main__":
    unittest.main()
