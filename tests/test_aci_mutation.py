from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

from game_agent.aci import (
    ACI_TOOL_NAMES,
    AciConfig,
    UnityAciController,
    UnityMutationExecutor,
)
from game_agent.context import ContextAssembler, ContextConfig


def result(
    *,
    status: str = "ok",
    returncode: int = 0,
    extra: dict | None = None,
) -> dict:
    payload = {"status": status}
    return {
        "output": json.dumps(payload),
        "returncode": returncode,
        "exception_info": "",
        "extra": {"aci": True, "structured": payload, **(extra or {})},
    }


class FakeQueryExecutor:
    def execute(self, action: dict) -> dict:
        if action["tool"] == "code_diagnostics":
            return result(extra={"structured": {"status": "partial", "diagnostics": []}})
        return result()


class FakeMutationExecutor:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, action: dict) -> dict:
        tool = action["tool"]
        self.calls.append(tool)
        if tool == "unity_script_patch":
            return result(extra={
                "aci_mutation": True,
                "checkpoint_id": "checkpoint-1",
                "changed_paths": ["Assets/Test.cs"],
            })
        if tool == "unity_recompile":
            return result(extra={"aci_control": True, "validation_modes": ["compile"]})
        if tool == "unity_validate":
            modes = action["arguments"]["modes"]
            return result(extra={"aci_control": True, "validation_modes": modes})
        return result()

    def metrics(self) -> dict:
        return {
            "typed_mutation_calls": 1,
            "escape_hatch_calls": 0,
            "escape_hatch_ratio": 0.0,
            "checkpoints_created": 1,
        }


class MutationExecutorTest(unittest.TestCase):
    def test_script_patch_is_hash_guarded_checkpointed_and_measured(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Test.cs"
            source.parent.mkdir(parents=True)
            source.write_text("class Test { int Value = 1; }\n", encoding="utf-8")
            before = source.read_bytes()
            executor = UnityMutationExecutor(
                project_root=project,
                artifact_root=project / "artifacts",
            )

            output = executor.execute({
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "Value = 1",
                    "new_text": "Value = 2",
                    "expected_sha256": hashlib.sha256(before).hexdigest(),
                    "evidence_node_ids": ["file"],
                },
            })

            self.assertEqual(0, output["returncode"])
            self.assertIn("Value = 2", source.read_text(encoding="utf-8"))
            manifest = (
                project / "artifacts" / output["extra"]["checkpoint_manifest"]
            )
            self.assertTrue(manifest.is_file())
            checkpoint = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(hashlib.sha256(before).hexdigest(), checkpoint["files"][0]["sha256"])
            self.assertEqual(1, executor.metrics()["typed_mutation_calls"])
            self.assertEqual(0.0, executor.metrics()["escape_hatch_ratio"])

            stale = executor.execute({
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "Value = 2",
                    "new_text": "Value = 3",
                    "expected_sha256": hashlib.sha256(before).hexdigest(),
                    "evidence_node_ids": ["file"],
                },
            })
            self.assertNotEqual(0, stale["returncode"])
            self.assertIn("Source hash changed", stale["exception_info"])

    def test_editor_bridge_uses_typed_unity_apis_and_save_refresh_contract(self):
        source = (
            Path(__file__).parents[1]
            / "src" / "game_agent" / "aci" / "editor" / "GameAgentAciBridge.cs"
        ).read_text(encoding="utf-8")
        for api in (
            "Undo.RegisterCreatedObjectUndo",
            "Undo.DestroyObjectImmediate",
            "Undo.AddComponent",
            "SerializedObject",
            "PrefabUtility.SaveAsPrefabAsset",
            "EditorSceneManager.SaveScene",
            "AssetDatabase.ImportAsset",
            "AssetDatabase.Refresh",
        ):
            self.assertIn(api, source)

    def test_temporary_editor_helper_cleanup_leaves_no_project_artifacts(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            (project / "Assets").mkdir()
            executor = UnityMutationExecutor(project_root=project, artifact_root=project / "artifacts")

            helper, created = executor._install_helper("Temporary.cs", "class Temporary {}")
            Path(f"{helper}.meta").write_text("fileFormatVersion: 2", encoding="utf-8")
            Path(f"{helper.parent}.meta").write_text("fileFormatVersion: 2", encoding="utf-8")
            executor._remove_helper(helper, created)

            self.assertFalse(helper.exists())
            self.assertFalse(Path(f"{helper}.meta").exists())
            self.assertFalse((project / "Assets" / "Editor").exists())
            self.assertFalse(Path(f"{project / 'Assets' / 'Editor'}.meta").exists())


class ExecutionProtocolTest(unittest.TestCase):
    def test_controller_enforces_read_checkpoint_diagnostics_reload_validation(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            context = ContextAssembler(ContextConfig(enabled=True), project_root=project)
            context.reset("Patch Test.cs", task_id="task")
            mutation = FakeMutationExecutor()
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(required_validation_modes=["editmode", "playmode"]),
                query_executor=FakeQueryExecutor(),
                mutation_executor=mutation,
            )
            action = {
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "a",
                    "new_text": "b",
                    "expected_sha256": "0" * 64,
                    "evidence_node_ids": ["file"],
                },
            }

            blocked = controller.execute(action)
            self.assertEqual("location_evidence_required", blocked["extra"]["guard"])

            context.record_verified_fact(
                "Read source file Assets/Test.cs.",
                sources=["source:Assets/Test.cs"],
                node_ids=["file"],
            )
            changed = controller.execute(action)
            self.assertEqual(0, changed["returncode"])
            self.assertEqual("static_diagnostics", controller.pending.stage)
            self.assertEqual(
                "previous_change_unverified",
                controller.execute(action)["extra"]["guard"],
            )
            self.assertEqual(
                "execution_protocol_incomplete",
                controller.guard_submission()["extra"]["guard"],
            )

            controller.execute({"tool": "code_diagnostics", "arguments": {}})
            self.assertEqual("recompile_or_hot_reload", controller.pending.stage)
            controller.execute({"tool": "unity_recompile", "arguments": {}})
            self.assertEqual("runtime_validation", controller.pending.stage)
            controller.execute({
                "tool": "unity_validate",
                "arguments": {"modes": ["editmode"]},
            })
            self.assertEqual("runtime_validation", controller.pending.stage)
            controller.execute({
                "tool": "unity_validate",
                "arguments": {"modes": ["playmode"]},
            })

            self.assertIsNone(controller.pending)
            self.assertIsNone(controller.guard_submission())
            self.assertEqual(1, len(controller.completed))
            self.assertTrue(context.evidence.verified())

    def test_public_tool_set_covers_typed_mutation_and_control_surface(self):
        expected = {
            "unity_gameobject_create",
            "unity_gameobject_delete",
            "unity_gameobject_rename",
            "unity_component_add",
            "unity_component_remove",
            "unity_serialized_property_set",
            "unity_prefab_create",
            "unity_asset_save",
            "unity_asset_import",
            "unity_script_patch",
            "unity_execute_csharp",
            "unity_recompile",
            "unity_hot_reload",
            "unity_validate",
        }
        self.assertTrue(expected <= ACI_TOOL_NAMES)


if __name__ == "__main__":
    unittest.main()
