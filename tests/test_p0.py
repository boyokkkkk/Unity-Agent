from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_agent.trajectory import TRAJECTORY_SCHEMA_VERSION, TrajectorySchemaError, validate_trajectory
from game_agent.unity_assets import audit_unity_assets
from game_agent.validation import UnityValidator, _run_process
from game_agent.workspace import create_task_workspace
from game_agent.processes import terminate_process_tree
from game_agent.services.worker import run_worker


def write_meta(path: Path, guid: str) -> None:
    Path(str(path) + ".meta").write_text(
        f"fileFormatVersion: 2\nguid: {guid}\n", encoding="utf-8"
    )


def create_unity_project(root: Path) -> Path:
    project = root / "UnityProject"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2021.3.45f1\n", encoding="utf-8"
    )
    assets = project / "Assets"
    assets.mkdir()
    script = assets / "Player.cs"
    script.write_text("public class Player {}\n", encoding="utf-8")
    write_meta(script, "1" * 32)
    scene = assets / "Main.unity"
    scene.write_text(
        "%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Script: {fileID: 11500000, guid: "
        + "1" * 32
        + ", type: 3}\n",
        encoding="utf-8",
    )
    write_meta(scene, "2" * 32)
    prefab = assets / "Player.prefab"
    prefab.write_text("%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_Name: Player\n", encoding="utf-8")
    write_meta(prefab, "3" * 32)
    return project


class UnityAssetAuditTest(unittest.TestCase):
    def test_valid_meta_scene_and_prefab_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            result = audit_unity_assets(create_unity_project(Path(directory)))

            self.assertEqual(result["status"], "passed")
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["stats"]["yaml_files"], 2)

    def test_missing_or_duplicate_meta_fails_and_external_guid_warns(self):
        with tempfile.TemporaryDirectory() as directory:
            project = create_unity_project(Path(directory))
            missing = project / "Assets" / "NoMeta.asset"
            missing.write_text(
                "%YAML 1.1\n--- !u!114 &1\nMonoBehaviour:\n  ref: {guid: " + "9" * 32 + "}\n",
                encoding="utf-8",
            )
            (project / "Assets" / "Duplicate.txt").write_text("duplicate", encoding="utf-8")
            write_meta(project / "Assets" / "Duplicate.txt", "1" * 32)
            orphan = project / "Assets" / "Gone.cs.meta"
            orphan.write_text("fileFormatVersion: 2\nguid: " + "4" * 32 + "\n", encoding="utf-8")

            result = audit_unity_assets(project)
            codes = {error["code"] for error in result["errors"]}

            self.assertEqual(result["status"], "failed")
            self.assertTrue({"missing_meta", "duplicate_guid", "orphan_meta"} <= codes)
            self.assertIn("unresolved_guid", {warning["code"] for warning in result["warnings"]})


class UnityValidatorTest(unittest.TestCase):
    def test_missing_editor_is_explicitly_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            result = UnityValidator(
                project, root / "validation", {"modes": ["compile"], "editor_path": str(root / "missing.exe")}
            ).run()

            self.assertEqual(result["status"], "skipped_unavailable")
            self.assertEqual(result["checks"][1]["status"], "skipped_unavailable")
            self.assertEqual(
                json.loads((root / "validation" / "summary.json").read_text(encoding="utf-8"))["status"],
                "skipped_unavailable",
            )

    def test_compile_editmode_and_playmode_produce_passed_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            commands: list[list[str]] = []

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                commands.append(arguments)
                if "-testResults" in arguments:
                    result_path = Path(arguments[arguments.index("-testResults") + 1])
                    result_path.write_text(
                        '<test-run result="Passed" total="1" passed="1" failed="0" skipped="0" />',
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(arguments, 0, stdout="validation passed")

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["compile", "editmode", "playmode"], "timeout_seconds": 5},
                runner=runner,
            ).run()

            self.assertEqual(result["status"], "passed")
            self.assertEqual([check["status"] for check in result["checks"]], ["passed"] * 4)
            self.assertTrue((root / "validation" / "editmode-results.xml").is_file())
            self.assertTrue((root / "validation" / "playmode-results.xml").is_file())
            self.assertIn("-quit", commands[0])
            self.assertNotIn("-quit", commands[1])
            self.assertNotIn("-quit", commands[2])
            self.assertEqual(result["checks"][2]["total_tests"], 1)

    def test_editor_failure_fails_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")
            runner = lambda arguments, timeout: subprocess.CompletedProcess(arguments, 1, stdout="compile error")

            result = UnityValidator(
                project, root / "validation", {"editor_path": str(editor), "modes": ["compile"]}, runner=runner
            ).run()

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["checks"][1]["returncode"], 1)

    def test_zero_exit_does_not_hide_failed_test_xml_or_compiler_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                if "-testResults" in arguments:
                    result_path = Path(arguments[arguments.index("-testResults") + 1])
                    result_path.write_text(
                        '<test-run result="Failed" total="2" passed="0" failed="2" skipped="0" />',
                        encoding="utf-8",
                    )
                    return subprocess.CompletedProcess(arguments, 0, stdout="tests completed")
                return subprocess.CompletedProcess(arguments, 0, stdout="error CS1002: ; expected")

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["compile", "editmode"]},
                runner=runner,
            ).run()

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["checks"][1]["error"], "Unity log contains compiler errors")
            self.assertEqual(result["checks"][2]["failed_tests"], 2)

    def test_zero_tests_and_missing_xml_are_distinct_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")
            calls = 0

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                nonlocal calls
                calls += 1
                if calls == 1:
                    result_path = Path(arguments[arguments.index("-testResults") + 1])
                    result_path.write_text(
                        '<test-run result="Passed" total="0" passed="0" failed="0" skipped="0" />',
                        encoding="utf-8",
                    )
                return subprocess.CompletedProcess(arguments, 0, stdout="")

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["editmode", "playmode"]},
                runner=runner,
            ).run()

            self.assertEqual(result["checks"][1]["error_code"], "zero_tests")
            self.assertEqual(result["checks"][2]["error_code"], "missing_test_results")

    def test_result_xml_can_pass_after_bounded_process_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                result_path = Path(arguments[arguments.index("-testResults") + 1])
                result_path.write_text(
                    '<test-run result="Passed" total="1" passed="1" failed="0" skipped="0" />',
                    encoding="utf-8",
                )
                completed = subprocess.CompletedProcess(arguments, 1, stdout="")
                completed.forced_termination = True
                completed.pid = 4321
                return completed

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["playmode"]},
                runner=runner,
            ).run()

            check = result["checks"][1]
            self.assertEqual(check["status"], "passed")
            self.assertTrue(check["forced_termination"])
            self.assertEqual(check["pid"], 4321)

    def test_timeout_has_machine_readable_failure_code(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                raise subprocess.TimeoutExpired(arguments, timeout, output="still running")

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["editmode"], "timeout_seconds": 1},
                runner=runner,
            ).run()

            check = result["checks"][1]
            self.assertEqual(check["status"], "timed_out")
            self.assertEqual(check["error_code"], "timeout")
            self.assertEqual((root / "validation" / "editmode.log").read_text(encoding="utf-8"), "still running")

    def test_real_runner_polls_xml_then_terminates_only_its_delayed_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "delayed_unity.py"
            results = root / "results.xml"
            script.write_text(
                "import pathlib, sys, time\n"
                "target = pathlib.Path(sys.argv[sys.argv.index('-testResults') + 1])\n"
                "target.write_text('<test-run result=\"Passed\" total=\"1\" passed=\"1\" failed=\"0\" skipped=\"0\" />', encoding='utf-8')\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )

            with (
                patch("game_agent.validation.TEST_PROCESS_EXIT_GRACE_SECONDS", 0.1),
                patch("game_agent.validation.PROCESS_TERMINATION_GRACE_SECONDS", 0.1),
            ):
                completed = _run_process(
                    [sys.executable, str(script), "-testResults", str(results)],
                    timeout=5,
                )

            self.assertTrue(completed.result_ready)
            self.assertTrue(completed.forced_termination)
            self.assertGreater(completed.pid, 0)
            self.assertTrue(results.is_file())

    def test_project_lock_is_not_reported_as_generic_process_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            def runner(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(
                    arguments,
                    1,
                    stdout="Aborting batchmode due to another Unity instance using this project.",
                )

            result = UnityValidator(
                project,
                root / "validation",
                {"editor_path": str(editor), "modes": ["compile"]},
                runner=runner,
            ).run()

            self.assertEqual(result["checks"][1]["error_code"], "project_locked")


class WorkspaceIsolationTest(unittest.TestCase):
    def test_copy_workspace_excludes_generated_dirs_and_does_not_touch_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            (project / "Library").mkdir()
            (project / "Library" / "cache.bin").write_bytes(b"cache")
            lease = create_task_workspace(project, root / "workspaces" / "run", mode="copy")
            try:
                isolated_script = lease.project_path / "Assets" / "Player.cs"
                isolated_script.write_text("changed\n", encoding="utf-8")
                self.assertFalse((lease.project_path / "Library").exists())
                self.assertEqual((project / "Assets" / "Player.cs").read_text(encoding="utf-8"), "public class Player {}\n")
            finally:
                workspace_root = lease.workspace_root
                lease.close()
            self.assertFalse(workspace_root.exists())

    def test_worker_runs_in_isolated_copy_and_returns_patch_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_unity_project(root)
            config = root / "config.json"
            artifacts = root / "artifacts" / "run"
            config.write_text(
                json.dumps(
                    {
                        "experiment": {
                            "config_id": "p0", "backend": "fixture", "target_project": str(project),
                            "tool": "powershell", "max_input_tokens": 100, "max_output_tokens": 100,
                            "max_total_tokens": 1000, "max_rounds": 2, "cost_limit": 1,
                        },
                        "model": {"model_name": "fixture"},
                        "environment": {"cwd": str(project)},
                        "agent": {
                            "system_template": "test", "instance_template": "{{ task }}",
                            "step_limit": 2, "cost_limit": 1,
                        },
                        "workspace": {"isolation": "copy", "root": str(root / "workspaces")},
                        "logging": {"events_path": "unused", "trajectory_path": "unused"},
                    }
                ),
                encoding="utf-8",
            )

            def fake_run(task: str, config_path: Path, *, run_id: str) -> dict:
                resolved = json.loads(config_path.read_text(encoding="utf-8"))
                isolated = Path(resolved["environment"]["cwd"])
                (isolated / "Assets" / "Player.cs").write_text("agent output\n", encoding="utf-8")
                return {"exit_status": "Submitted", "submission": "done"}

            with patch("game_agent.services.worker.run", side_effect=fake_run):
                run_worker("run", "fixture", str(config), str(project), str(artifacts))

            self.assertEqual((project / "Assets" / "Player.cs").read_text(encoding="utf-8"), "public class Player {}\n")
            self.assertIn("+agent output", (artifacts / "diff.patch").read_text(encoding="utf-8"))
            self.assertEqual(json.loads((artifacts / "result.json").read_text(encoding="utf-8"))["status"], "submitted")
            self.assertFalse((root / "workspaces" / "run").exists())

    def test_git_worktree_overlays_dirty_and_untracked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = root / "repository"
            project = create_unity_project(repository)
            subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "initial"], cwd=repository, check=True, capture_output=True)
            dirty = project / "Assets" / "Player.cs"
            dirty.write_text("dirty input\n", encoding="utf-8")
            untracked = project / "Assets" / "New.cs"
            untracked.write_text("untracked input\n", encoding="utf-8")

            lease = create_task_workspace(project, root / "workspaces" / "run", mode="auto")
            try:
                self.assertEqual((lease.project_path / "Assets" / "Player.cs").read_text(encoding="utf-8"), "dirty input\n")
                self.assertEqual((lease.project_path / "Assets" / "New.cs").read_text(encoding="utf-8"), "untracked input\n")
                (lease.project_path / "Assets" / "Player.cs").write_text("agent output\n", encoding="utf-8")
                self.assertEqual(dirty.read_text(encoding="utf-8"), "dirty input\n")
            finally:
                workspace_root = lease.workspace_root
                lease.close()
            self.assertFalse(workspace_root.exists())


class TrajectorySchemaTest(unittest.TestCase):
    def test_stable_envelope_accepts_extensions_and_rejects_missing_messages(self):
        trajectory = {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "trajectory_format": "mini-swe-agent-1.1",
            "info": {
                "framework_version": "test",
                "exit_status": "Submitted",
                "submission": "done",
                "model_stats": {},
                "config": {},
            },
            "messages": [{"role": "system", "content": "test"}],
            "turn_results": [],
            "applied_skills": [],
            "extension": {"allowed": True},
        }
        self.assertIs(validate_trajectory(trajectory), trajectory)
        response_trajectory = {**trajectory, "messages": [{"object": "response", "output": []}]}
        self.assertIs(validate_trajectory(response_trajectory), response_trajectory)
        with self.assertRaises(TrajectorySchemaError):
            validate_trajectory({key: value for key, value in trajectory.items() if key != "messages"})


class ProcessTreeTest(unittest.TestCase):
    def test_windows_termination_contract_targets_descendants(self):
        completed = subprocess.CompletedProcess([], 0, stdout="")
        with patch("game_agent.processes.os.name", "nt"), patch(
            "game_agent.processes.subprocess.run", return_value=completed
        ) as invoked:
            terminate_process_tree(1234)

        self.assertEqual(invoked.call_args.args[0], ["taskkill", "/PID", "1234", "/T", "/F"])


if __name__ == "__main__":
    unittest.main()
