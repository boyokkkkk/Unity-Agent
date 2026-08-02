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
    EvidenceActionCompiler,
    LOCALIZATION_TOOL_NAMES,
    VALIDATION_TOOL_NAMES,
    UnityAciController,
    UnityMutationExecutor,
    StructuredQueryExecutor,
    select_tool_exposure,
)
from game_agent.context import ContextAssembler, ContextConfig, WorkingSetEntry


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
    def test_script_patch_preserves_crlf_without_double_translation(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Test.cs"
            source.parent.mkdir(parents=True)
            original = b"class Test {\r\n    int Value = 1;\r\n}\r\n"
            source.write_bytes(original)
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
                    "expected_sha256": hashlib.sha256(original).hexdigest(),
                    "evidence_node_ids": ["file"],
                },
            })

            self.assertEqual(0, output["returncode"])
            changed = source.read_bytes()
            self.assertNotIn(b"\r\r\n", changed)
            self.assertEqual(original.count(b"\r\n"), changed.count(b"\r\n"))

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

    def test_checkpoint_restore_supports_bounded_compile_repair(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Test.cs"
            source.parent.mkdir(parents=True)
            source.write_text("class Test { int Value = 1; }\n", encoding="utf-8")
            executor = UnityMutationExecutor(
                project_root=project,
                artifact_root=project / "artifacts",
            )
            checkpoint = executor.create_checkpoint(
                ["Assets/Test.cs"], operation="unity_script_patch"
            )
            source.write_text("class Test { BROKEN }\n", encoding="utf-8")

            restored = executor.restore_checkpoint(checkpoint["checkpoint_id"])

            self.assertEqual(["Assets/Test.cs"], restored)
            self.assertEqual(
                "class Test { int Value = 1; }\n",
                source.read_text(encoding="utf-8"),
            )

    def test_transaction_rolls_back_authorized_and_unauthorized_delta_atomically(self):
        class EscapingExecutor(UnityMutationExecutor):
            def _script_patch(self, args):
                authorized = self.project_root / "Assets" / "Test.cs"
                unauthorized = self.project_root / "Assets" / "Escape.cs"
                authorized.write_text("class Test { int Value = 2; }\n", encoding="utf-8")
                unauthorized.write_text("class Escape {}\n", encoding="utf-8")
                return self._ok("unity_script_patch", {"status": "ok"})

        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Test.cs"
            source.parent.mkdir(parents=True)
            original = b"class Test { int Value = 1; }\n"
            source.write_bytes(original)
            executor = EscapingExecutor(
                project_root=project,
                artifact_root=project / "artifacts",
            )
            output = executor.execute({
                "tool": "unity_script_patch",
                "_authorized_paths": ["Assets/Test.cs"],
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "Value = 1",
                    "new_text": "Value = 2",
                    "expected_sha256": hashlib.sha256(original).hexdigest(),
                    "evidence_node_ids": ["file"],
                },
            })

            self.assertEqual(-2, output["returncode"])
            self.assertEqual(
                "unauthorized_mutation_rolled_back",
                output["extra"]["structured"]["error_code"],
            )
            self.assertEqual(original, source.read_bytes())
            self.assertFalse((project / "Assets" / "Escape.cs").exists())
            transaction = output["extra"]["mutation_transaction"]
            self.assertEqual("rolled_back_unauthorized", transaction["status"])
            self.assertEqual(["Assets/Escape.cs"], transaction["unauthorized_paths"])
            self.assertTrue((project / "artifacts" / output["extra"]["mutation_diff"]).is_file())

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
    def test_filesystem_query_fallback_and_artifact_ablation_are_real(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets/Scripts/KitchenGameManager.cs"
            source.parent.mkdir(parents=True)
            source.write_text(
                "class KitchenGameManager { void GameInput_OnInteraction() {} }",
                encoding="utf-8",
            )
            context = ContextAssembler(ContextConfig(enabled=False), project_root=project)
            context.reset("find state interaction", task_id="filesystem-fallback")
            executor = StructuredQueryExecutor(
                context,
                project_root=project,
                artifact_root=project / "artifacts",
                evidence_artifact_enabled=False,
            )

            search = executor.execute({
                "tool": "code_symbol_search",
                "arguments": {"query": "KitchenGameManager interaction"},
            })
            rows = search["extra"]["structured"]["results"]
            self.assertEqual("Assets/Scripts/KitchenGameManager.cs", rows[0]["path"])
            read = executor.execute({
                "tool": "code_file_read",
                "arguments": {"node_id": rows[0]["id"]},
            })
            self.assertEqual(0, read["returncode"])
            self.assertNotIn("evidence_artifact_path", read["extra"])
            self.assertFalse((project / "artifacts/evidence-artifacts").exists())

    def test_submission_contract_ablation_exposes_early_submit(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            context = ContextAssembler(ContextConfig(enabled=True), project_root=project)
            context.reset("repair", task_id="no-contract")
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(workflow_enabled=True, submission_contract_enabled=False),
                query_executor=FakeQueryExecutor(),
                mutation_executor=FakeMutationExecutor(),
            )

            self.assertIn("submit", controller.tool_exposure().tool_names)
            self.assertIsNone(controller.guard_submission())

    def test_typed_mutation_ablation_routes_prepared_patch_to_escape_hatch(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets/Test.cs"
            source.parent.mkdir(parents=True)
            source.write_text("class Test { int Value = 1; }", encoding="utf-8")
            context = ContextAssembler(ContextConfig(enabled=True), project_root=project)
            context.reset("repair", task_id="no-typed")
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(typed_mutations_enabled=False),
                query_executor=FakeQueryExecutor(),
                mutation_executor=FakeMutationExecutor(),
            )
            action = controller._escape_hatch_patch_action({
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "Value = 1",
                    "new_text": "Value = 2",
                    "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "evidence_node_ids": ["file"],
                },
            })

            self.assertEqual("unity_execute_csharp", action["tool"])
            self.assertEqual(["Assets/Test.cs"], action["arguments"]["target_paths"])
            self.assertIn("Value = 2", action["arguments"]["code"])

    def test_validation_gate_ablation_completes_without_control_calls(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            context = ContextAssembler(ContextConfig(enabled=True), project_root=project)
            context.reset("repair", task_id="no-validation")
            mutation = FakeMutationExecutor()
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(validation_gates_enabled=False),
                query_executor=FakeQueryExecutor(),
                mutation_executor=mutation,
            )
            context.record_verified_fact(
                "Read source file Assets/Test.cs.",
                sources=["source:Assets/Test.cs"],
                node_ids=["file"],
            )

            output = controller.execute({
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "a",
                    "new_text": "b",
                    "expected_sha256": "0" * 64,
                    "evidence_node_ids": ["file"],
                },
            })

            self.assertEqual(0, output["returncode"])
            self.assertIsNone(controller.pending)
            self.assertTrue(controller.completed[0]["validation_skipped_by_ablation"])
            self.assertEqual(["unity_script_patch"], mutation.calls)

    def test_evidence_action_compiler_distinguishes_range_sha_and_failed_reads(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "Test.cs"
            source.parent.mkdir(parents=True)
            source.write_text("\n".join(f"line {index}" for index in range(1, 301)), encoding="utf-8")
            context = ContextAssembler(ContextConfig(auto_locate=False), project_root=project)
            context.reset("Inspect Test implementation", task_id="compiler")
            context.working_set.add(WorkingSetEntry(
                node_id="file",
                kind="CSHARP_FILE",
                name="Test.cs",
                path="Assets/Test.cs",
                relevance=1.0,
            ))
            compiler = EvidenceActionCompiler(context, project_root=project)
            first = {
                "tool": "code_file_read",
                "arguments": {
                    "node_id": "file",
                    "path": "Assets/Test.cs",
                    "start_line": 1,
                    "end_line": 10,
                },
            }
            first_output = result(extra={
                "structured": {
                    "status": "ok",
                    "node": {"id": "file"},
                    "path": "Assets/Test.cs",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "start_line": 1,
                    "end_line": 10,
                    "total_lines": 300,
                    "content": "\n".join(f"line {index}" for index in range(1, 11)),
                },
                "evidence_claim": "Read Test.cs lines 1-10.",
                "evidence_sources": ["source:Assets/Test.cs:1-10"],
            })

            compiler.observe(first, first_output)

            self.assertFalse(compiler.before_action(first).allowed)
            different_range = {
                "tool": "code_file_read",
                "arguments": {"path": "Assets/Test.cs", "start_line": 11, "end_line": 20},
            }
            self.assertTrue(compiler.before_action(different_range).allowed)
            replan = compiler.replan_output(first, reason="duplicate")
            alternatives = replan["extra"]["structured"]["admissible_next_actions"]
            self.assertTrue(any(
                item["tool"] == "code_file_read"
                and item["arguments"].get("start_line") == 11
                for item in alternatives
            ))
            self.assertFalse(any(
                slot["id"] == "implementation_source"
                for slot in compiler.open_slots()
            ))

            source.write_text(source.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8")
            self.assertTrue(compiler.before_action(first).allowed)

            failed = {
                "tool": "code_file_read",
                "arguments": {"path": "Assets/Missing.cs", "start_line": 1, "end_line": 10},
            }
            compiler.observe(failed, result(status="error", returncode=-2))
            self.assertTrue(compiler.before_action(failed).allowed)
            self.assertTrue(any(
                slot["id"] == "failed_source_read"
                for slot in compiler.open_slots()
            ))

    def test_empty_read_does_not_complete_evidence_and_replan_prefers_search_match(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            context = ContextAssembler(ContextConfig(auto_locate=False), project_root=project)
            context.reset(
                "Fix the game state manager countdown transition",
                task_id="semantic-success",
            )
            compiler = EvidenceActionCompiler(context, project_root=project)
            search = {
                "tool": "unity_asset_search",
                "arguments": {"query": "game state"},
            }
            compiler.observe(search, result(extra={
                "structured": {
                    "status": "ok",
                    "query": "game state",
                    "total": 3,
                    "results": [
                        {
                            "id": "input",
                            "kind": "CSHARP_FILE",
                            "name": "GameInput.cs",
                            "path": "Assets/Scripts/GameInput.cs",
                        },
                        {
                            "id": "manager",
                            "kind": "CSHARP_FILE",
                            "name": "KitchenGameManager.cs",
                            "path": "Assets/Scripts/KitchenGameManager.cs",
                        },
                        {
                            "id": "option",
                            "kind": "CSHARP_FILE",
                            "name": "OptionUI.cs",
                            "path": "Assets/Scripts/UI/OptionUI.cs",
                        },
                    ],
                },
                "node_ids": ["input", "manager", "option"],
                "evidence_claim": "Observed indexed game-state candidates.",
                "evidence_sources": ["graph:input", "graph:manager", "graph:option"],
            }))
            missing = {
                "tool": "code_file_read",
                "arguments": {"path": "Assets/Scripts/GameManager.cs"},
            }
            compiler.observe(missing, result(extra={
                "structured": {
                    "status": "ok",
                    "total": 0,
                    "results": [],
                    "reason": "No matching indexed C# file or symbol.",
                },
            }))

            signature = compiler.action_signature(missing)
            self.assertNotIn(signature, compiler.completed_actions)
            self.assertNotIn(signature, compiler.disabled_actions)
            self.assertTrue(compiler.before_action(missing).allowed)
            self.assertTrue(any(
                slot["id"] == "failed_source_read"
                for slot in compiler.open_slots()
            ))
            replan = compiler.replan_output(missing, reason="repeated empty read")
            alternatives = replan["extra"]["structured"]["admissible_next_actions"]
            self.assertEqual(
                "Assets/Scripts/KitchenGameManager.cs",
                alternatives[0]["arguments"]["path"],
            )
            self.assertEqual("manager", alternatives[0]["arguments"]["node_id"])

    def test_path_only_read_does_not_unlock_implementation_profile(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            source = project / "Assets" / "GameInput.cs"
            source.parent.mkdir(parents=True)
            source.write_text("public class GameInput {}", encoding="utf-8")
            context = ContextAssembler(ContextConfig(auto_locate=False), project_root=project)
            context.reset("Fix state transition", task_id="phase-gate")
            compiler = EvidenceActionCompiler(context, project_root=project)
            action = {
                "tool": "code_file_read",
                "arguments": {"path": "Assets/GameInput.cs"},
            }
            compiler.observe(action, result(extra={
                "structured": {
                    "status": "ok",
                    "path": "Assets/GameInput.cs",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "start_line": 1,
                    "end_line": 1,
                    "total_lines": 1,
                    "content": "public class GameInput {}",
                },
                "evidence_claim": "Read GameInput.cs.",
                "evidence_sources": ["source:Assets/GameInput.cs:1-1"],
            }))

            open_slots = [slot["id"] for slot in compiler.open_slots()]
            exposure = select_tool_exposure(
                phase="evidence_verification",
                unresolved_slot_ids=open_slots,
                working_paths=["Assets/GameInput.cs"],
            )
            self.assertIn("implementation_source", open_slots)
            self.assertEqual("localization", exposure.profile)

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
            exposure = controller.tool_exposure()
            self.assertEqual("validation", exposure.profile)
            self.assertTrue(exposure.validation_locked)
            self.assertEqual({"code_diagnostics", "artifact_read"}, set(exposure.tool_names))
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
            self.assertEqual(
                {"unity_recompile"},
                set(controller.tool_exposure().tool_names),
            )
            controller.execute({"tool": "unity_recompile", "arguments": {}})
            self.assertEqual("runtime_validation", controller.pending.stage)
            self.assertIn(
                "unity_validate",
                controller.tool_exposure().tool_names,
            )
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

    def test_automatic_validation_advances_all_post_patch_gates(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get("TEMP")) as directory:
            project = Path(directory)
            context = ContextAssembler(ContextConfig(enabled=True), project_root=project)
            context.reset("Patch Test.cs", task_id="automatic-validation")
            mutation = FakeMutationExecutor()
            controller = UnityAciController(
                context,
                project_root=project,
                config=AciConfig(
                    automatic_validation_enabled=True,
                    required_validation_modes=["editmode", "playmode"],
                ),
                query_executor=FakeQueryExecutor(),
                mutation_executor=mutation,
            )
            context.record_verified_fact(
                "Read source file Assets/Test.cs.",
                sources=["source:Assets/Test.cs"],
                node_ids=["file"],
            )
            changed = controller.execute({
                "tool": "unity_script_patch",
                "arguments": {
                    "path": "Assets/Test.cs",
                    "old_text": "a",
                    "new_text": "b",
                    "expected_sha256": "0" * 64,
                    "evidence_node_ids": ["file"],
                },
            })
            self.assertEqual(0, changed["returncode"])

            validation = controller._run_automatic_validation()

            self.assertEqual("complete", validation["status"])
            self.assertEqual(
                ["code_diagnostics", "unity_recompile", "unity_validate"],
                [step["tool"] for step in validation["steps"]],
            )
            self.assertIsNone(controller.pending)
            self.assertEqual(
                ["unity_script_patch", "unity_recompile", "unity_validate"],
                mutation.calls,
            )

    def test_dynamic_exposure_has_three_minimal_profiles(self):
        localization = select_tool_exposure(
            phase="evidence_verification",
            unresolved_slot_ids=["implementation_source"],
            working_paths=["Assets/Scripts/Test.cs"],
        )
        implementation = select_tool_exposure(
            phase="evidence_verification",
            unresolved_slot_ids=[],
            working_paths=["Assets/Scripts/Test.cs"],
        )
        validation = select_tool_exposure(
            phase="implementation",
            unresolved_slot_ids=[],
            working_paths=["Assets/Scripts/Test.cs"],
            pending_stage="static_diagnostics",
        )

        self.assertEqual("localization", localization.profile)
        self.assertEqual(LOCALIZATION_TOOL_NAMES, set(localization.tool_names))
        self.assertEqual("implementation", implementation.profile)
        self.assertIn("unity_script_patch", implementation.tool_names)
        self.assertNotIn("unity_component_add", implementation.tool_names)
        self.assertEqual("validation", validation.profile)
        self.assertTrue(validation.validation_locked)
        self.assertEqual({"code_diagnostics", "artifact_read"}, set(validation.tool_names))

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
