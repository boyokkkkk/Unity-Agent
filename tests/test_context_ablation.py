from __future__ import annotations

import tempfile
import json
from pathlib import Path

from game_agent.aci.causal_facts import build_causal_fact_matrix
from game_agent.context import ContextAssembler, ContextConfig
from game_agent.project_graph.retrieval import LocalizationRetriever
from game_agent.project_graph.schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph
from game_agent.baseline_runner import StateEventBaselineRunner


def _graph(root: Path) -> ProjectGraph:
    path = "Assets/Scripts/Manager.cs"
    target = root / path
    target.parent.mkdir(parents=True)
    target.write_text("class Manager { void Begin() {} int state; }", encoding="utf-8")
    graph = ProjectGraph(project_path=str(root))
    graph.add_node(Node("file", NodeKind.CSHARP_FILE, "Manager.cs", path))
    graph.add_node(Node("method", NodeKind.METHOD, "Begin", path, {"declaring_type": "Manager"}))
    graph.add_node(Node("state", NodeKind.FIELD, "state", path, {"declaring_type": "Manager"}))
    graph.add_edge(Edge("method", "state", EdgeKind.WRITES_STATE))
    return graph


def test_graph_retrieval_switch_forces_a0_without_disabling_store() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        result = LocalizationRetriever(_graph(root), root).retrieve(
            "Manager Begin", "A2", graph_retrieval_enabled=False
        )
        assert result.variant == "A0"
        assert result.files
        assert result.treatment["graph_score_contributions"] == 0
        assert result.treatment["retrieval_opportunity"] == 1


def test_causal_edge_switch_filters_network_and_fact_matrix() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        graph = _graph(root)
        result = LocalizationRetriever(graph, root).retrieve(
            "Manager Begin state", "A2", causal_edges_enabled=False
        )
        assert result.treatment["source_causal_edges"] == 1
        assert result.treatment["returned_causal_edges"] == 0
        assert result.treatment["suppressed_causal_edges"] == 1
        matrix = build_causal_fact_matrix(graph, causal_edges_enabled=False)
        assert all(fact.predicate != "WRITES_STATE" for fact in matrix.facts)


def test_context_assembly_switch_preserves_raw_tool_messages() -> None:
    assembler = ContextAssembler(ContextConfig(context_assembly_enabled=False))
    messages = [
        {"role": "system", "content": "system"},
        {"role": "tool", "content": "exact direct tool result"},
    ]
    assert assembler.assemble(messages, raw_input_tokens=10, max_input_tokens=100) == messages
    treatment = assembler.metrics()["treatment"]
    assert treatment["assembly_opportunities"] == 1
    assert treatment["assembly_injections"] == 0
    assert treatment["assembly_bypasses"] == 1
    assert treatment["direct_tool_results_preserved"] == 1


def test_generated_suite_has_unique_treatments_and_fixed_controls() -> None:
    root = Path(__file__).resolve().parents[1] / "configs/context_ablation"
    configs = [json.loads((root / f"c{i}.json").read_text(encoding="utf-8")) for i in range(5)]
    assert len(json.loads((root / "pilot-schedule.json").read_text())["runs"]) == 10
    assert len(json.loads((root / "formal-schedule.json").read_text())["runs"]) == 150
    assert len({config["context"]["graph_sha256"] for config in configs}) == 1
    assert all(config["experiment"]["max_total_tokens"] == 163840 for config in configs)
    vectors = {
        tuple(config["context"][key] for key in (
            "graph_retrieval_enabled", "semantic_search_enabled",
            "causal_edges_enabled", "context_assembly_enabled",
        ))
        for config in configs
    }
    assert len(vectors) == 5


def test_treatment_activation_rejects_unactivated_c1() -> None:
    config = {"context_condition": "C1"}
    valid, evidence = StateEventBaselineRunner._treatment_activation(config, [])
    assert not valid
    assert evidence["condition"] == "C1"
