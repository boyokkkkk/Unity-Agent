from __future__ import annotations

import json
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from game_agent.aci import QUERY_TOOL_NAMES, StructuredQueryExecutor
from game_agent.context import ContextAssembler, ContextConfig, EvidenceStatus, ProjectContextStore
from game_agent.framework.agents.default import DefaultAgent
from game_agent.framework.environments.local import LocalEnvironment
from game_agent.framework.models.utils.actions_toolcall import AGENT_TOOLS, parse_toolcall_actions
from game_agent.framework.models.utils.actions_toolcall_response import parse_response_actions
from game_agent.project_graph.schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph


def aci_graph(project: Path) -> ProjectGraph:
    source = project / "Assets" / "Scripts" / "KitchenManager.cs"
    source.parent.mkdir(parents=True)
    source.write_text(
        "class KitchenManager { void StartCountdown() { ShowCountdown(); } void ShowCountdown() {} }",
        encoding="utf-8",
    )
    scene = project / "Assets" / "Scenes" / "Game.unity"
    scene.parent.mkdir(parents=True)
    scene.write_text("%YAML 1.1\n", encoding="utf-8")
    prefab = project / "Assets" / "Prefabs" / "CountdownPanel.prefab"
    prefab.parent.mkdir(parents=True)
    prefab.write_text("%YAML 1.1\n", encoding="utf-8")
    graph = ProjectGraph(project_path=str(project), metadata={"project_revision": "aci-1"})
    nodes = [
        Node("file", NodeKind.CSHARP_FILE, "KitchenManager.cs", "Assets/Scripts/KitchenManager.cs"),
        Node("type", NodeKind.MONO_BEHAVIOUR, "KitchenManager", "Assets/Scripts/KitchenManager.cs"),
        Node("start", NodeKind.METHOD, "StartCountdown", "Assets/Scripts/KitchenManager.cs", {"line": 1, "declaring_type": "KitchenManager"}),
        Node("show", NodeKind.METHOD, "ShowCountdown", "Assets/Scripts/KitchenManager.cs", {"line": 1, "declaring_type": "KitchenManager"}),
        Node("scene", NodeKind.SCENE, "Game", "Assets/Scenes/Game.unity"),
        Node("prefab", NodeKind.PREFAB, "CountdownPanel", "Assets/Prefabs/CountdownPanel.prefab"),
        Node("go", NodeKind.GAME_OBJECT, "CountdownCanvas", "Assets/Scenes/Game.unity", {"hierarchy_path": "UI/CountdownCanvas", "active": True}),
        Node("component", NodeKind.COMPONENT, "KitchenManager", "Assets/Scenes/Game.unity", {"game_object_id": "go", "type_name": "KitchenManager", "code_symbol_id": "type", "script_path": "Assets/Scripts/KitchenManager.cs"}),
    ]
    for node in nodes:
        graph.add_node(node)
    for edge in [
        Edge("start", "show", EdgeKind.CALLS),
        Edge("scene", "go", EdgeKind.CONTAINS),
        Edge("component", "go", EdgeKind.ATTACHED_TO),
        Edge("go", "prefab", EdgeKind.PREFAB_SOURCE),
        Edge("component", "show", EdgeKind.UNITY_EVENT_CALL, {"event_field": "onStart"}),
    ]:
        graph.add_edge(edge)
    return graph


class StructuredQueryExecutorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("TEMP"))
        self.project = Path(self.temporary.name)
        self.artifacts = self.project / "artifacts"
        self.artifacts.mkdir()
        store = ProjectContextStore.from_graph(aci_graph(self.project), project_root=self.project)
        self.context = ContextAssembler(
            ContextConfig(auto_locate=False), project_root=self.project,
            artifact_root=self.artifacts, project_store=store,
        )
        self.context.reset("Find the countdown UI", task_id="aci-task")
        self.executor = StructuredQueryExecutor(
            self.context, project_root=self.project, artifact_root=self.artifacts,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call(self, tool: str, **arguments):
        action = {"tool": tool, "arguments": arguments}
        output = self.executor.execute(action)
        self.context.record_tool_transition([action], [output], [])
        return json.loads(output["output"]), output

    def test_search_read_and_references_update_working_set_and_evidence(self):
        assets, _ = self.call("unity_asset_search", query="CountdownPanel", limit=5)
        objects, _ = self.call("unity_object_search", query="CountdownCanvas", limit=5)
        detail, _ = self.call("unity_object_read", node_id="go")
        refs, _ = self.call("unity_ref_search", node_id="scene", direction="dependencies", max_depth=2)
        symbols, _ = self.call("code_symbol_search", query="ShowCountdown", limit=5)
        code_refs, _ = self.call("code_find_references", node_id="show", direction="incoming")

        self.assertEqual("prefab", assets["results"][0]["id"])
        self.assertEqual("go", objects["results"][0]["id"])
        self.assertEqual("CountdownCanvas", detail["object"]["name"])
        self.assertTrue(any(item["node"]["id"] == "go" for item in refs["results"]))
        self.assertEqual("show", symbols["results"][0]["id"])
        self.assertEqual({"CALLS", "UNITY_EVENT_CALL"}, {item["edge_kind"] for item in code_refs["results"]})
        self.assertTrue({"go", "component", "show"}.issubset(self.context.working_set.entries))
        self.assertTrue(any(item.status == EvidenceStatus.SOURCE_VERIFIED for item in self.context.evidence.items.values()))
        self.assertTrue(all(item.evidence_ids for item in self.context.working_set.entries.values()))

    def test_object_list_diagnostics_editor_status_and_artifact_read_are_truthful(self):
        listed, _ = self.call("unity_object_list", asset_path="Assets/Scenes/Game.unity")
        diagnostics, _ = self.call("code_diagnostics", scope="workspace")
        status, _ = self.call("unity_editor_status")
        artifact = self.artifacts / "tool-outputs" / "sample.txt"
        artifact.parent.mkdir()
        artifact.write_text("one\ntwo\nthree\n", encoding="utf-8")
        content, _ = self.call("artifact_read", artifact_ref="tool-outputs/sample.txt", start_line=2, end_line=3)

        self.assertEqual(2, listed["total"])
        self.assertFalse(diagnostics["compiler_diagnostics_available"])
        self.assertFalse(diagnostics["compile_verified"])
        self.assertFalse(status["bridge_connected"])
        self.assertEqual("two\nthree", content["content"])
        escaped, output = self.call("artifact_read", artifact_ref="../outside.txt")
        self.assertEqual("error", escaped["status"])
        self.assertNotEqual(0, output["returncode"])

    def test_precise_asset_and_code_reads_create_patch_preconditions(self):
        asset, _ = self.call("unity_asset_read", node_id="scene")
        source, _ = self.call("code_file_read", node_id="file", start_line=1, end_line=1)

        raw = (self.project / "Assets" / "Scripts" / "KitchenManager.cs").read_bytes()
        self.assertEqual("scene", asset["asset"]["id"])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), source["sha256"])
        verified_ids = {
            node_id
            for evidence in self.context.evidence.verified()
            for node_id in evidence.node_ids
        }
        self.assertTrue({"scene", "file"} <= verified_ids)

    def test_queries_without_graph_report_unavailable_without_false_evidence(self):
        context = ContextAssembler(ContextConfig(auto_locate=False), project_root=self.project)
        context.reset("query", task_id="no-graph")
        executor = StructuredQueryExecutor(context, project_root=self.project)
        output = executor.execute({"tool": "unity_asset_search", "arguments": {"query": "Player"}})
        self.assertEqual("unavailable", json.loads(output["output"])["status"])
        self.assertEqual({}, context.evidence.items)


class StructuredToolProtocolTest(unittest.TestCase):
    def test_both_model_protocols_expose_and_parse_query_tools(self):
        names = {tool["function"]["name"] for tool in AGENT_TOOLS}
        self.assertTrue(QUERY_TOOL_NAMES.issubset(names))
        chat_call = SimpleNamespace(
            id="call-1",
            function=SimpleNamespace(name="code_symbol_search", arguments='{"query":"KitchenManager"}'),
        )
        actions = parse_toolcall_actions([chat_call], format_error_template="{{ error }}")
        self.assertEqual("code_symbol_search", actions[0]["tool"])
        self.assertEqual("KitchenManager", actions[0]["arguments"]["query"])

        responses = parse_response_actions(
            [{"type": "function_call", "id": "call-2", "name": "unity_object_read", "arguments": '{"node_id":"go"}'}],
            format_error_template="{{ error }}",
        )
        self.assertEqual("unity_object_read", responses[0]["tool"])
        self.assertEqual("go", responses[0]["arguments"]["node_id"])

    def test_default_agent_routes_query_without_powershell_and_records_p1_state(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            artifacts = project / "artifacts"
            store = ProjectContextStore.from_graph(aci_graph(project), project_root=project)
            context = ContextAssembler(
                ContextConfig(auto_locate=False), project_root=project,
                artifact_root=artifacts, project_store=store,
            )
            model = _QueryThenSubmitModel()
            events = []
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=str(project), artifact_dir=str(artifacts)),
                system_template="system", instance_template="{{task}}",
                context_assembler=context, step_limit=4,
                event_sink=lambda name, **data: events.append({"event": name, **data}),
            )

            result = agent.run("Find ShowCountdown")

            self.assertEqual("Submitted", result["exit_status"])
            self.assertEqual("show", next(iter(context.working_set.entries)))
            self.assertEqual(1, context.metrics()["structured_query_calls"])
            self.assertEqual(1, context.metrics()["structured_query_evidence"])
            self.assertTrue(context.memory.artifact_references)
            tool_events = [event for event in events if event["event"] in {"tool_start", "tool_end"}]
            self.assertEqual(["tool_start", "tool_end"], [event["event"] for event in tool_events])
            end = tool_events[-1]
            self.assertEqual("code_symbol_search", end["tool"])
            self.assertEqual(64, len(end["arguments_hash"]))
            self.assertTrue(end["action_signature"].startswith("code_symbol_search:"))
            self.assertEqual(["show"], end["node_ids"])
            self.assertTrue(end["evidence_ids"])
            self.assertEqual(0, end["returncode"])
            self.assertEqual("", end["blocked_reason"])
            preflight = [
                event for event in events if event["event"] == "model_preflight"
            ]
            self.assertTrue(preflight)
            self.assertTrue(all(
                event["tool_profile"] == "localization"
                for event in preflight
            ))
            self.assertTrue(all(
                event["tool_schema_tokens"] > 0
                for event in preflight
            ))
            self.assertTrue(all(
                event["exposed_tool_count"] == len(QUERY_TOOL_NAMES.intersection({
                    "code_symbol_search",
                    "unity_asset_search",
                    "code_find_references",
                    "code_file_read",
                    "artifact_read",
                }))
                for event in preflight
            ))

    def test_repeated_aci_action_emits_structured_replan_instead_of_hard_stop(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            artifacts = project / "artifacts"
            store = ProjectContextStore.from_graph(aci_graph(project), project_root=project)
            context = ContextAssembler(
                ContextConfig(auto_locate=False), project_root=project,
                artifact_root=artifacts, project_store=store,
            )
            events = []
            agent = DefaultAgent(
                _RepeatReadModel(),
                LocalEnvironment(cwd=str(project), artifact_dir=str(artifacts)),
                system_template="system", instance_template="{{task}}",
                context_assembler=context, step_limit=4, max_repeated_actions=2,
                event_sink=lambda name, **data: events.append({"event": name, **data}),
            )

            result = agent.run("Read the target")

            ends = [event for event in events if event["event"] == "tool_end"]
            self.assertNotEqual("RepeatedActionExceeded", result["exit_status"])
            self.assertEqual([0, -2, -2, -2], [event["returncode"] for event in ends])
            self.assertFalse(ends[0]["blocked"])
            self.assertTrue(all(
                event["blocked_reason"] == "completed_action_disabled"
                for event in ends[1:]
            ))
            self.assertTrue(all(
                event["admissible_action_signatures"]
                for event in ends[1:]
            ))
            self.assertEqual(4, len({
                event["tool_call_id"] for event in ends
            }))

    def test_agent_can_accept_admissible_alternative_after_structured_replan(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            artifacts = project / "artifacts"
            store = ProjectContextStore.from_graph(aci_graph(project), project_root=project)
            context = ContextAssembler(
                ContextConfig(auto_locate=False), project_root=project,
                artifact_root=artifacts, project_store=store,
            )
            events = []
            agent = DefaultAgent(
                _ReplanRecoveryModel(),
                LocalEnvironment(cwd=str(project), artifact_dir=str(artifacts)),
                system_template="system", instance_template="{{task}}",
                context_assembler=context, step_limit=5,
                event_sink=lambda name, **data: events.append({"event": name, **data}),
            )

            result = agent.run("Read then follow references")

            self.assertEqual("Submitted", result["exit_status"])
            ends = [event for event in events if event["event"] == "tool_end"]
            self.assertEqual([0, -2, 0], [event["returncode"] for event in ends])
            self.assertTrue(ends[1]["admissible_action_signatures"])
            third_start = [
                event for event in events
                if event["event"] == "tool_start" and event["tool"] == "code_find_references"
            ][0]
            self.assertIn(
                third_start["action_signature"],
                third_start["admissible_action_signatures"],
            )


class _QueryThenSubmitModel:
    def __init__(self):
        self.config = SimpleNamespace(model_name="query-test")
        self.calls = 0
        self.available_tool_names = ()

    def set_available_tool_names(self, tool_names):
        self.available_tool_names = tuple(tool_names)

    def estimate_tool_schema_tokens(self):
        return len(self.available_tool_names) * 10

    def estimate_input_tokens(self, messages):
        return len(json.dumps(messages, default=str))

    def query(self, messages, **kwargs):
        del messages, kwargs
        self.calls += 1
        if self.calls == 1:
            actions = [{"tool": "code_symbol_search", "arguments": {"query": "ShowCountdown", "limit": 1}, "tool_call_id": "q1"}]
        else:
            actions = [{"tool": "submit", "answer": "done", "tool_call_id": "q2"}]
        return {"role": "assistant", "content": "", "extra": {"actions": actions, "cost": 0.0, "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars=None):
        del template_vars
        return [{"role": "tool", "tool_call_id": action["tool_call_id"], "content": output["output"], "extra": output.get("extra", {}) | {"returncode": output["returncode"]}} for action, output in zip(message["extra"]["actions"], outputs)]

    def get_template_vars(self, **kwargs):
        return kwargs

    def serialize(self):
        return {"info": {}}


class _RepeatReadModel(_QueryThenSubmitModel):
    def query(self, messages, **kwargs):
        del messages, kwargs
        self.calls += 1
        actions = [{
            "tool": "code_file_read",
            "arguments": {"path": "Assets/Scripts/KitchenManager.cs"},
            "tool_call_id": f"read-{self.calls}",
        }]
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": actions,
                "cost": 0.0,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": self.calls * 2,
            },
        }


class _ReplanRecoveryModel(_QueryThenSubmitModel):
    def query(self, messages, **kwargs):
        del messages, kwargs
        self.calls += 1
        if self.calls <= 2:
            actions = [{
                "tool": "code_file_read",
                "arguments": {"path": "Assets/Scripts/KitchenManager.cs"},
                "tool_call_id": f"read-{self.calls}",
            }]
        elif self.calls == 3:
            actions = [{
                "tool": "code_find_references",
                "arguments": {"node_id": "file", "direction": "both"},
                "tool_call_id": "references",
            }]
        else:
            actions = [{"tool": "submit", "answer": "recovered", "tool_call_id": "submit"}]
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": actions,
                "cost": 0.0,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": self.calls * 2,
            },
        }


if __name__ == "__main__":
    unittest.main()
