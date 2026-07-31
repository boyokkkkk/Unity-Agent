from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from game_agent.project_graph.builder import resolve_code_asset_links
from game_agent.project_graph.agent_audit import GraphUsageAnalyzer
from game_agent.project_graph.evaluation import (
    LOCALIZATION_TASK_SCHEMA,
    LocalizationEvaluator,
    LocalizationTask,
    LocalizationTaskSet,
)
from game_agent.project_graph.retrieval import LocalizationRetriever
from game_agent.project_graph.roslyn import RoslynCodeParser
from game_agent.project_graph.schema import (
    GRAPH_SCHEMA_VERSION,
    Edge,
    EdgeKind,
    Node,
    NodeKind,
    ProjectGraph,
)
from game_agent.project_graph.store import ProjectGraphStore, to_networkx
from game_agent.project_graph.statistics import (
    bootstrap_mean_ci,
    holm_adjust,
    mcnemar_exact,
    paired_permutation_test,
)
from game_agent.project_graph.unity_export import (
    EDITOR_EXPORT_SCHEMA_VERSION,
    unity_export_to_graph,
)


def synthetic_graph(project: Path) -> ProjectGraph:
    source = project / "Assets" / "Scripts" / "KitchenManager.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class KitchenManager { void StartCountdown() { ShowCountdown(); } "
        "void ShowCountdown() {} object countdownCanvas; }",
        encoding="utf-8",
    )
    graph = ProjectGraph(project_path=str(project))
    nodes = [
        Node("file", NodeKind.CSHARP_FILE, "KitchenManager.cs", "Assets/Scripts/KitchenManager.cs"),
        Node("type", NodeKind.MONO_BEHAVIOUR, "KitchenManager", "Assets/Scripts/KitchenManager.cs"),
        Node("start", NodeKind.METHOD, "StartCountdown", "Assets/Scripts/KitchenManager.cs", {"declaring_type": "KitchenManager"}),
        Node("show", NodeKind.METHOD, "ShowCountdown", "Assets/Scripts/KitchenManager.cs", {"declaring_type": "KitchenManager"}),
        Node("field", NodeKind.FIELD, "countdownCanvas", "Assets/Scripts/KitchenManager.cs", {"declaring_type": "KitchenManager", "serialized": True}),
        Node("scene", NodeKind.SCENE, "GameScene", "Assets/Scenes/GameScene.unity"),
        Node("prefab", NodeKind.PREFAB, "CountdownPanel", "Assets/Prefabs/CountdownPanel.prefab"),
        Node("go", NodeKind.GAME_OBJECT, "CountdownCanvas", "Assets/Scenes/GameScene.unity", {"hierarchy_path": "UI/CountdownCanvas"}),
        Node("component", NodeKind.COMPONENT, "KitchenManager", "Assets/Scenes/GameScene.unity", {"type_name": "KitchenManager", "code_symbol_id": "type", "script_path": "Assets/Scripts/KitchenManager.cs"}),
        Node("asset", NodeKind.ASSET, "CountdownSprite", "Assets/Sprites/Countdown.png"),
    ]
    for node in nodes:
        graph.add_node(node)
    for edge in [
        Edge("start", "show", EdgeKind.CALLS),
        Edge("component", "go", EdgeKind.ATTACHED_TO),
        Edge("scene", "go", EdgeKind.CONTAINS),
        Edge("go", "prefab", EdgeKind.PREFAB_SOURCE),
        Edge("field", "asset", EdgeKind.SERIALIZED_REF, {"property_path": "countdownCanvas"}),
        Edge("component", "show", EdgeKind.UNITY_EVENT_CALL, {"event_field": "onStart"}),
    ]:
        graph.add_edge(edge)
    return graph


class ProjectGraphSchemaTest(unittest.TestCase):
    def test_round_trip_and_six_edge_contract(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            root = Path(directory)
            graph = synthetic_graph(root)
            self.assertEqual([], graph.validate(require_six_edge_kinds=True))
            path = root / "graph.json"
            graph.save(path)
            restored = ProjectGraph.load(path)
            self.assertEqual(GRAPH_SCHEMA_VERSION, restored.to_dict()["schema_version"])
            self.assertEqual(graph.stats(), restored.stats())

    def test_sqlite_and_networkx_preserve_typed_edges(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            root = Path(directory)
            graph = synthetic_graph(root)
            store = ProjectGraphStore(root / "graph.sqlite3")
            store.save(graph)
            self.assertEqual(1, store.stats()["edges"]["SERIALIZED_REF"])
            self.assertEqual(
                "go",
                store.neighbors("component", edge_kinds=[EdgeKind.ATTACHED_TO], direction="out")[0]["target"],
            )
            network = to_networkx(graph)
            self.assertEqual(10, network.number_of_nodes())
            self.assertEqual(6, network.number_of_edges())


class UnityExportConversionTest(unittest.TestCase):
    def test_editor_export_maps_asset_relations_and_resolves_code_symbols(self):
        data = {
            "schema_version": EDITOR_EXPORT_SCHEMA_VERSION,
            "unity_version": "2021.3.45f1",
            "assets": [
                {"id": "scene", "kind": "SCENE", "name": "GameScene", "path": "Assets/GameScene.unity", "guid": "1"},
                {"id": "prefab", "kind": "PREFAB", "name": "Panel", "path": "Assets/Panel.prefab", "guid": "2"},
                {"id": "asset", "kind": "ASSET", "name": "Icon", "path": "Assets/Icon.png", "guid": "3"},
            ],
            "game_objects": [
                {"id": "go", "name": "Canvas", "asset_id": "scene", "asset_path": "Assets/GameScene.unity", "hierarchy_path": "UI/Canvas", "parent_id": "", "active": True, "tag": "Untagged", "layer": 5}
            ],
            "components": [
                {"id": "component", "name": "Controller", "game_object_id": "go", "asset_path": "Assets/GameScene.unity", "type_name": "Controller", "assembly_name": "Assembly-CSharp", "script_path": "Assets/Controller.cs", "script_guid": "4", "enabled": True}
            ],
            "serialized_refs": [
                {"source_component_id": "component", "source_type": "Controller", "property_path": "icon", "target_id": "asset", "target_kind": "ASSET", "target_path": "Assets/Icon.png"}
            ],
            "unity_event_calls": [
                {"source_component_id": "component", "event_field": "clicked", "target_id": "component", "target_type": "Controller", "method_name": "Handle", "listener_index": 0}
            ],
            "prefab_sources": [
                {"game_object_id": "go", "prefab_id": "prefab", "prefab_path": "Assets/Panel.prefab"}
            ],
        }
        graph = unity_export_to_graph(data)
        graph.add_node(Node("type", NodeKind.MONO_BEHAVIOUR, "Controller", "Assets/Controller.cs"))
        graph.add_node(Node("field", NodeKind.FIELD, "icon", "Assets/Controller.cs", {"declaring_type": "Controller"}))
        graph.add_node(Node("method", NodeKind.METHOD, "Handle", "Assets/Controller.cs", {"declaring_type": "Controller"}))
        graph.add_edge(Edge("method", "method", EdgeKind.CALLS))
        resolved = resolve_code_asset_links(graph)
        self.assertEqual(1, resolved["component_code_links"])
        self.assertEqual(1, resolved["serialized_fields_resolved"])
        self.assertEqual(1, resolved["unity_events_resolved"])
        self.assertEqual([], graph.validate(require_six_edge_kinds=True))

    def test_exporter_source_uses_required_editor_apis(self):
        source = (
            Path(__file__).parents[1]
            / "src"
            / "game_agent"
            / "project_graph"
            / "editor"
            / "ProjectGraphExporter.cs"
        ).read_text(encoding="utf-8")
        for required in (
            "AssetDatabase",
            "SerializedObject",
            "PrefabUtility",
            "EditorSceneManager",
            "GlobalObjectId",
            "UnityEventBase",
        ):
            self.assertIn(required, source)


class RoslynParserTest(unittest.TestCase):
    def test_real_roslyn_parser_extracts_symbols_fields_and_calls(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Controller.cs"
            source.parent.mkdir()
            source.write_text(
                """
                using UnityEngine;
                using UnityEngine.UI;
                public class Controller : MonoBehaviour {
                    [SerializeField] private GameObject panel;
                    [SerializeField] private Button button;
                    private void Awake() { button.onClick.AddListener(Show); }
                    public void Begin() { Show(); }
                    private void Show() {}
                }
                """,
                encoding="utf-8",
            )
            graph = RoslynCodeParser().parse(project, output_path=project / "roslyn.json")
            self.assertEqual("roslyn", graph.metadata["code_parser"])
            self.assertTrue(any(node.kind == NodeKind.MONO_BEHAVIOUR for node in graph.nodes.values()))
            self.assertTrue(any(node.kind == NodeKind.FIELD and node.attributes["serialized"] for node in graph.nodes.values()))
            self.assertEqual(1, graph.stats()["edge_kinds"]["CALLS"])
            self.assertEqual(1, graph.stats()["edge_kinds"]["UNITY_EVENT_CALL"])


class LocalizationAblationTest(unittest.TestCase):
    def test_role_aware_diversity_collapses_paths_and_enforces_test_quota(self):
        rows = [
            {"id": "test-file", "path": "Assets/Tests/PlayMode/KitchenManagerTests.cs", "kind": "CSHARP_FILE", "score": 1.0},
            {"id": "test-type", "path": "Assets/Tests/PlayMode/KitchenManagerTests.cs", "kind": "CLASS", "score": 0.99},
            {"id": "other-test", "path": "Assets/Tests/EditMode/OtherTests.cs", "kind": "METHOD", "score": 0.98},
            {"id": "manager", "path": "Assets/Scripts/KitchenGameManager.cs", "kind": "CSHARP_FILE", "score": 0.90},
            {"id": "tutorial", "path": "Assets/Scripts/UI/TutorialUI.cs", "kind": "CSHARP_FILE", "score": 0.80},
            {"id": "input", "path": "Assets/Scripts/GameInput.cs", "kind": "CSHARP_FILE", "score": 0.70},
        ]

        collapsed = LocalizationRetriever._diversify_rows(
            rows, limit=4, strategy="path_collapse", max_test_candidates=1, mmr_lambda=0.72
        )
        diversified = LocalizationRetriever._diversify_rows(
            rows, limit=4, strategy="role_mmr", max_test_candidates=1, mmr_lambda=0.72
        )

        self.assertEqual(4, len({item["path"] for item in collapsed}))
        self.assertLessEqual(sum(item["role"] == "test" for item in diversified), 1)
        self.assertTrue(any(item["id"] == "manager" for item in diversified))
        self.assertGreaterEqual(len({item["subsystem"] for item in diversified}), 3)

    def test_a0_a1_a2_use_progressively_richer_context(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph = synthetic_graph(project)
            retriever = LocalizationRetriever(graph, project)
            query = "KitchenManager StartCountdown countdown Canvas prefab"
            a0 = retriever.retrieve(query, "A0")
            a1 = retriever.retrieve(query, "A1")
            a2 = retriever.retrieve(query, "A2")
            self.assertEqual("Assets/Scripts/KitchenManager.cs", a0.files[0]["path"])
            self.assertEqual([], a0.game_objects)
            self.assertEqual([], a1.game_objects)
            self.assertTrue(any(item["name"] == "CountdownCanvas" for item in a2.game_objects))
            self.assertTrue(a2.dependency_paths)

    def test_evaluator_reports_recall_precision_and_dependency_paths(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph = synthetic_graph(project)
            tasks = LocalizationTaskSet.model_validate(
                {
                    "schema_version": LOCALIZATION_TASK_SCHEMA,
                    "project_path": str(project),
                    "ks": [1, 5],
                    "tasks": [
                        {
                            "id": "state-event",
                            "query": "KitchenManager StartCountdown countdown Canvas",
                            "gold_files": ["Assets/Scripts/KitchenManager.cs"],
                            "gold_game_objects": ["CountdownCanvas"],
                            "gold_assets": ["Assets/Scenes/GameScene.unity"],
                            "gold_dependency_paths": [
                                {
                                    "source_contains": "KitchenManager",
                                    "target_contains": "GameScene",
                                    "edge_kinds": ["CODE_COMPONENT", "ATTACHED_TO", "CONTAINS"],
                                }
                            ],
                        }
                    ],
                }
            )
            result = LocalizationEvaluator(graph, tasks).run()
            self.assertEqual({"A0", "A1", "A2"}, set(result["aggregate"]))
            self.assertEqual(0.0, result["aggregate"]["A0"]["gameobject_recall@5"])
            self.assertGreater(result["aggregate"]["A2"]["gameobject_recall@5"], 0.0)
            self.assertIn("confidence_intervals", result["inference"])
            self.assertIn("A2_vs_A0", result["inference"]["paired_tests"])

    def test_diversity_evaluator_reports_injected_defects_and_localization_metrics(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            graph = synthetic_graph(project)
            tasks = LocalizationTaskSet.model_validate(
                {
                    "schema_version": LOCALIZATION_TASK_SCHEMA,
                    "project_path": str(project),
                    "ks": [1, 4],
                    "tasks": [
                        {
                            "id": "injected-state-event",
                            "query": "KitchenManager StartCountdown countdown",
                            "gold_files": ["Assets/Scripts/KitchenManager.cs"],
                            "injected_defect": {
                                "kind": "script_event_missing",
                                "target_path": "Assets/Scripts/KitchenManager.cs",
                                "root_cause_file": "Assets/Scripts/KitchenManager.cs",
                            },
                        }
                    ],
                }
            )

            report = LocalizationEvaluator(graph, tasks).run_diversity(
                bootstrap_resamples=20,
                bootstrap_seed=7,
            )

            self.assertEqual(1, report["injected_defect_count"])
            self.assertEqual({"D0", "D1", "D2", "D3"}, set(report["aggregate"]))
            self.assertIn("root_cause_recall@4", report["aggregate"]["D3"])
            self.assertIn("candidate_distinct_path_ratio@4", report["aggregate"]["D3"])
            self.assertIn("D3_vs_D0", report["inference"]["paired_tests"])


class LocalizationStatisticsTest(unittest.TestCase):
    def test_bootstrap_is_deterministic_and_contains_estimate(self):
        first = bootstrap_mean_ci([0.0, 0.5, 1.0], resamples=500, seed=7)
        second = bootstrap_mean_ci([0.0, 0.5, 1.0], resamples=500, seed=7)
        self.assertEqual(first, second)
        self.assertLessEqual(first["lower"], first["estimate"])
        self.assertGreaterEqual(first["upper"], first["estimate"])

    def test_paired_tests_report_task_level_direction_and_exact_p_values(self):
        permutation = paired_permutation_test([1.0, 1.0, 0.5], [0.0, 0.0, 0.5])
        self.assertEqual(2, permutation["wins"])
        self.assertEqual(1, permutation["ties"])
        self.assertGreater(permutation["mean_difference"], 0.0)
        mcnemar = mcnemar_exact([True, True, False], [False, False, False])
        self.assertEqual(2, mcnemar["left_only"])
        self.assertEqual(0, mcnemar["right_only"])
        adjusted = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.2})
        self.assertGreaterEqual(adjusted["a"], 0.01)
        self.assertGreaterEqual(adjusted["b"], adjusted["a"])


class AgentGraphUsageAuditTest(unittest.TestCase):
    def test_detects_graph_first_adoption_and_scores_final_scope(self):
        task = LocalizationTask.model_validate(
            {
                "id": "audit",
                "query": "countdown",
                "gold_files": ["Assets/Scripts/KitchenManager.cs"],
                "gold_game_objects": ["Canvas/Countdown"],
                "gold_assets": ["Assets/GameScene.unity"],
            }
        )
        events = [
            {
                "seq": 10,
                "event": "tool_start",
                "command": "game-agent-graph query --variant A2",
                "command_category": "other",
                "accessed_files": [],
            },
            {
                "seq": 11,
                "event": "tool_end",
                "command": "game-agent-graph query --variant A2",
                "returncode": 0,
            },
            {
                "seq": 20,
                "event": "tool_start",
                "command": "Get-Content Assets/Scripts/KitchenManager.cs",
                "command_category": "read",
                "accessed_files": ["Assets/Scripts/KitchenManager.cs"],
            },
        ]
        submission = json.dumps(
            {
                "files": ["Assets/Scripts/KitchenManager.cs"],
                "game_objects": ["Canvas/Countdown"],
                "assets": ["Assets/GameScene.unity"],
                "dependency_paths": [],
                "graph_evidence": ["SERIALIZED_REF"],
            }
        )
        audit = GraphUsageAnalyzer().analyze(
            events=events,
            submission=submission,
            task=task,
            graph_result={
                "files": [{"path": "Assets/Scripts/KitchenManager.cs"}],
            },
        )
        self.assertTrue(audit["correctly_applied"])
        self.assertTrue(audit["graph_tool"]["graph_before_manual_navigation"])
        self.assertEqual(1.0, audit["adoption"]["recommended_file_adoption_rate"])
        self.assertEqual(1.0, audit["metrics"]["file_recall"])


if __name__ == "__main__":
    unittest.main()
