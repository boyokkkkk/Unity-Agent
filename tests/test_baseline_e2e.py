from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from game_agent.baseline_runner import (
    BASELINE_SCHEMA_VERSION,
    BaselineCase,
    StateEventBaselineRunner,
    TARGET_SCRIPT,
    inject_hidden_oracle,
    inject_state_event_defect,
    patch_matches_oracle,
    remove_hidden_oracle,
)
from game_agent.logging import ExperimentLogger
from game_agent.trajectory import TRAJECTORY_SCHEMA_VERSION, UPSTREAM_TRAJECTORY_FORMAT, write_trajectory


MANAGER_SOURCE = """using System;
using UnityEngine;

public class KitchenGameManager : MonoBehaviour
{
    public event EventHandler OnStateChanged;
    private enum State { WaitingToStart, CountdownToStart, GamePlaying, GameOver }
    private State state = State.WaitingToStart;

    private void GameInput_OnInteraction(object sender, EventArgs e)
    {
        if (state == State.WaitingToStart)
        {
            state = State.CountdownToStart;
            OnStateChanged?.Invoke(this, EventArgs.Empty);
        }
    }

    public bool IsCountdownToStartActive() { return state == State.CountdownToStart; }
    public bool IsGamePlaying() { return state == State.GamePlaying; }
}
"""


def create_project(root: Path) -> Path:
    project = root / "SourceProject"
    (project / "ProjectSettings").mkdir(parents=True)
    (project / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 2021.3.45f1\n", encoding="utf-8"
    )
    target = project / TARGET_SCRIPT
    target.parent.mkdir(parents=True)
    target.write_text(MANAGER_SOURCE, encoding="utf-8")
    ui = project / "Assets" / "Scripts" / "UI"
    ui.mkdir()
    (ui / "TutorialUI.cs").write_text("public class TutorialUI {}\n", encoding="utf-8")
    (ui / "GameStartCountdownUI.cs").write_text(
        "public class GameStartCountdownUI {}\n", encoding="utf-8"
    )
    tests = project / "Assets" / "Tests"
    tests.mkdir()
    return project


def create_config(root: Path, project: Path) -> Path:
    config = root / "config.json"
    config.write_text(
        json.dumps(
            {
                "experiment": {
                    "config_id": "fixture",
                    "backend": "fixture",
                    "target_project": str(project),
                    "tool": "powershell",
                    "max_input_tokens": 12000,
                    "max_output_tokens": 2048,
                    "max_total_tokens": 81920,
                    "max_rounds": 40,
                    "cost_limit": 3.0,
                    "seed": 42,
                },
                "model": {
                    "model_name": "fixture/model",
                    "model_class": "litellm",
                    "model_kwargs": {},
                    "cost_tracking": "ignore_errors",
                },
                "environment": {"cwd": str(project), "timeout": 5},
                "agent": {
                    "system_template": "system",
                    "instance_template": "{{task}}",
                    "step_limit": 40,
                    "cost_limit": 3.0,
                },
                "skills": {"enabled": True, "paths": []},
                "validation": {"enabled": True},
                "logging": {
                    "events_path": str(root / "unused-events.jsonl"),
                    "trajectory_path": str(root / "unused-trajectory.json"),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return config


class FakeValidator:
    def __init__(self, project, artifact_dir, config, *, event_sink=None):
        self.project = Path(project)
        self.artifact_dir = Path(artifact_dir)
        self.config = config
        self.event_sink = event_sink

    def run(self):
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        hidden = self.artifact_dir.name == "hidden"
        if hidden:
            self.assert_oracle_visible()
        passed = patch_matches_oracle(self.project)
        checks = [{"name": "asset_integrity", "status": "passed"}]
        for mode in self.config["modes"]:
            status = "passed" if passed else "failed"
            check = {"name": mode, "status": status}
            if mode != "compile":
                xml = self.artifact_dir / f"{mode}-results.xml"
                xml.write_text(
                    f'<test-run result="{"Passed" if passed else "Failed"}" total="1" '
                    f'passed="{1 if passed else 0}" failed="{0 if passed else 1}" skipped="0" />',
                    encoding="utf-8",
                )
                check.update(total_tests=1, passed_tests=1 if passed else 0, failed_tests=0 if passed else 1)
            checks.append(check)
            if self.event_sink:
                self.event_sink("validation_start", validation=mode)
                self.event_sink("validation_end", validation=mode, **check)
        summary = {
            "schema_version": "game-agent-unity-validation-v1",
            "status": "passed" if passed else "failed",
            "checks": checks,
        }
        (self.artifact_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary

    def assert_oracle_visible(self):
        oracle = self.project / "Assets" / "Tests" / "BaselineOracle"
        if not oracle.is_dir():
            raise AssertionError("hidden oracle was not injected before hidden validation")


def fake_successful_agent(task: str, config_path: Path, *, run_id: str) -> dict:
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    if config["skills"]["enabled"] is not False or config["skills"]["paths"]:
        raise AssertionError("baseline did not disable skills")
    project = Path(config["environment"]["cwd"])
    target = project / TARGET_SCRIPT
    text = target.read_text(encoding="utf-8")
    text = text.replace(
        "state = State.CountdownToStart;\n            \n",
        "state = State.CountdownToStart;\n            OnStateChanged?.Invoke(this, EventArgs.Empty);\n",
        1,
    )
    target.write_text(text, encoding="utf-8")

    events = Path(config["logging"]["events_path"])
    logger = ExperimentLogger(events, run_id=run_id, config_id=config["experiment"]["config_id"])
    logger.emit("task_start", task=task)
    logger.emit("turn_start", request=task, turn=1)
    logger.emit(
        "tool_start",
        command=f'Get-Content "{TARGET_SCRIPT.as_posix()}"',
        command_category="read",
        accessed_files=[TARGET_SCRIPT.as_posix()],
    )
    logger.emit(
        "tool_end",
        command=f'Set-Content "{TARGET_SCRIPT.as_posix()}"',
        command_category="write",
        accessed_files=[TARGET_SCRIPT.as_posix()],
        returncode=0,
        output="",
        output_chars=0,
    )
    logger.emit("model_usage", prompt_tokens=200, completion_tokens=40, total_tokens=240)
    logger.emit("turn_end", exit_status="Submitted", submission="已恢复状态事件并验证。", turn=1)
    logger.emit("task_end", status="closed", turn=1)

    write_trajectory(
        Path(config["logging"]["trajectory_path"]),
        {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
            "trajectory_format": UPSTREAM_TRAJECTORY_FORMAT,
            "messages": [{"role": "user", "content": task}],
            "turn_results": [],
            "applied_skills": [],
            "info": {
                "framework_version": "fixture",
                "exit_status": "Submitted",
                "submission": "已恢复状态事件并验证。",
                "model_stats": {
                    "prompt_tokens": 200,
                    "completion_tokens": 40,
                    "total_tokens": 240,
                },
                "config": {},
            },
        },
    )
    return {
        "exit_status": "Submitted",
        "submission": "已恢复状态事件并验证。",
        "token_usage": {"prompt_tokens": 200, "completion_tokens": 40, "total_tokens": 240},
    }


class BaselineFixtureTest(unittest.TestCase):
    def test_baseline_variant_clears_configured_graph_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root)
            config = create_config(root, project)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["context"] = {"enabled": True, "graph_path": "missing/project-graph.json"}
            config.write_text(json.dumps(payload), encoding="utf-8")
            artifact_dir = root / "artifacts" / "baseline"
            artifact_dir.mkdir(parents=True)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            prepared, _ = StateEventBaselineRunner(
                BaselineCase(
                    source_project=project,
                    config_path=config,
                    artifact_dir=artifact_dir,
                    editor_path=editor,
                )
            )._prepare_config(project, "baseline")

            self.assertFalse(prepared["context"]["enabled"])
            self.assertEqual(prepared["context"]["graph_path"], "")

    def test_innovation_variant_preserves_graph_context_and_aci(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root)
            config = create_config(root, project)
            graph = root / "project-graph.json"
            graph.write_text("{}", encoding="utf-8")
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload["context"] = {"enabled": True, "graph_path": str(graph)}
            payload["aci"] = {"enabled": True, "typed_mutations_enabled": True}
            payload["model"]["structured_query_tools_enabled"] = True
            config.write_text(json.dumps(payload), encoding="utf-8")
            artifact_dir = root / "artifacts" / "innovation"
            artifact_dir.mkdir(parents=True)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")

            prepared, _ = StateEventBaselineRunner(
                BaselineCase(
                    source_project=project,
                    config_path=config,
                    artifact_dir=artifact_dir,
                    editor_path=editor,
                    variant="innovation",
                )
            )._prepare_config(project, "innovation")

            self.assertTrue(prepared["skills"]["enabled"])
            self.assertTrue(prepared["context"]["enabled"])
            self.assertEqual(Path(prepared["context"]["graph_path"]), graph.resolve())
            self.assertTrue(prepared["model"]["structured_query_tools_enabled"])
            self.assertTrue(prepared["aci"]["typed_mutations_enabled"])
            self.assertEqual(Path(prepared["aci"]["editor_path"]), editor.resolve())

    def test_defect_and_hidden_oracle_are_reversible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root)
            artifacts = root / "artifacts"
            artifacts.mkdir()
            original = (project / TARGET_SCRIPT).read_text(encoding="utf-8")

            manifest = inject_state_event_defect(project, artifacts)

            self.assertEqual(manifest["schema_version"], BASELINE_SCHEMA_VERSION)
            self.assertFalse(patch_matches_oracle(project))
            oracle = inject_hidden_oracle(project, artifacts)
            self.assertFalse(oracle["visible_to_agent"])
            self.assertTrue((project / "Assets" / "Tests" / "BaselineOracle").is_dir())
            self.assertTrue(remove_hidden_oracle(project))
            self.assertFalse((project / "Assets" / "Tests" / "BaselineOracle").exists())
            self.assertNotEqual((project / TARGET_SCRIPT).read_text(encoding="utf-8"), original)

    def test_complete_orchestration_produces_verified_report_without_touching_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root)
            config = create_config(root, project)
            editor = root / "Unity.exe"
            editor.write_text("fixture", encoding="utf-8")
            artifact_dir = root / "artifacts" / "state-event-v1" / "fixture-run"
            source_before = (project / TARGET_SCRIPT).read_text(encoding="utf-8")

            report = StateEventBaselineRunner(
                BaselineCase(
                    source_project=project,
                    config_path=config,
                    artifact_dir=artifact_dir,
                    editor_path=editor,
                ),
                agent_runner=fake_successful_agent,
                validator_factory=FakeValidator,
            ).run()

            self.assertTrue(report["experiment_valid"])
            self.assertTrue(report["verified_success"])
            self.assertTrue(report["no_skill_evidence"])
            self.assertTrue(report["source_project_unchanged"])
            self.assertTrue(report["hidden_oracle_cleaned"])
            self.assertEqual((project / TARGET_SCRIPT).read_text(encoding="utf-8"), source_before)
            self.assertFalse((artifact_dir / "workspace").exists())
            for relative in (
                "case.json",
                "config.json",
                "defect-manifest.json",
                "agent-result.json",
                "events.jsonl",
                "conversation.jsonl",
                "trajectory.json",
                "diff.patch",
                "stage-metrics.json",
                "baseline-report.json",
                "baseline-report.md",
                "validation/public/summary.json",
                "validation/hidden/summary.json",
                "validation/hidden/oracle-manifest.json",
            ):
                self.assertTrue((artifact_dir / relative).is_file(), relative)
            metrics = json.loads((artifact_dir / "stage-metrics.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["context"]["total_tokens"], 240)
            self.assertEqual(metrics["navigation"]["root_cause_rank"], 1)
            conversation = [
                json.loads(line)
                for line in (artifact_dir / "conversation.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(conversation[0]["role"], "user")
            self.assertEqual(conversation[-1]["kind"], "final")


if __name__ == "__main__":
    unittest.main()
