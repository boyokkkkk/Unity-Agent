from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from game_agent.baseline import (
    StageAnalyzer,
    classify_command,
    enrich_tool_event,
    extract_command_paths,
    project_conversation,
    replay_aci_tool_events,
)
from game_agent.logging import ExperimentLogger


RELEVANT_FILES = (
    "Assets/Scripts/KitchenGameManager.cs",
    "Assets/Scripts/UI/TutorialUI.cs",
    "Assets/Scripts/UI/GameStartCountdownUI.cs",
)
ROOT_CAUSE = "Assets/Scripts/KitchenGameManager.cs"


def event(seq: int, elapsed_ms: int, name: str, **data) -> dict:
    return {"seq": seq, "elapsed_ms": elapsed_ms, "event": name, **data}


def tool_start(seq: int, elapsed_ms: int, command: str) -> dict:
    return event(seq, elapsed_ms, "tool_start", command=command, **enrich_tool_event(command))


def tool_end(
    seq: int,
    elapsed_ms: int,
    command: str,
    *,
    output: str = "",
    digest: str = "",
    returncode: int = 0,
) -> dict:
    enriched = enrich_tool_event(command, {"output": output})
    return event(
        seq,
        elapsed_ms,
        "tool_end",
        command=command,
        returncode=returncode,
        output=output,
        output_chars=len(output),
        output_sha256=digest,
        **enriched,
    )


class BaselineObservabilityUnitTest(unittest.TestCase):
    def test_logger_records_monotonic_and_elapsed_time(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            logger = ExperimentLogger(path, run_id="run", config_id="config")

            first = logger.emit("task_start")
            second = logger.emit("turn_start", request="repair")

            self.assertLessEqual(first["monotonic_ns"], second["monotonic_ns"])
            self.assertLessEqual(first["elapsed_ms"], second["elapsed_ms"])
            persisted = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(persisted[1]["elapsed_ms"], second["elapsed_ms"])

    def test_command_classification_and_path_extraction_are_behavior_neutral(self):
        read = 'Get-Content -LiteralPath "Assets\\Scripts\\KitchenGameManager.cs"'
        write = 'Set-Content -LiteralPath "Assets\\Scripts\\KitchenGameManager.cs" -Value $source'
        validate = '& "D:\\Unity\\Editor\\Unity.exe" -runTests -testPlatform EditMode'

        self.assertEqual(classify_command(read), "read")
        self.assertEqual(classify_command(write), "write")
        self.assertEqual(classify_command(validate), "validation")
        self.assertEqual(extract_command_paths(read), ["Assets/Scripts/KitchenGameManager.cs"])
        self.assertEqual(enrich_tool_event(read, {"output": "abc"})["observation_chars"], 3)

    def test_empty_trajectory_metrics_are_defined_without_division_errors(self):
        metrics = StageAnalyzer(relevant_files=RELEVANT_FILES, root_cause_file=ROOT_CAUSE).analyze(
            [event(1, 0, "turn_start", request="repair"), event(2, 10, "turn_end", exit_status="Failed")]
        )

        self.assertEqual(metrics["navigation"]["navigation_precision"], 0.0)
        self.assertEqual(metrics["navigation"]["unrelated_file_ratio"], 0.0)
        self.assertEqual(metrics["context"]["repeated_observation_ratio"], 0.0)
        self.assertTrue(metrics["outcome"]["missing_final_answer"])

    def test_conversation_projection_has_task_progress_and_final_answer(self):
        records = [
            event(1, 0, "turn_start", request="修复状态 UI"),
            tool_start(2, 10, 'rg "OnStateChanged" Assets'),
            tool_start(3, 20, 'Set-Content "Assets\\Scripts\\KitchenGameManager.cs"'),
            event(4, 30, "validation_start", validation="editmode"),
            event(5, 40, "turn_end", exit_status="Submitted", submission="已修复并通过测试。"),
        ]

        conversation = project_conversation(records)

        self.assertEqual(conversation[0]["role"], "user")
        self.assertEqual([item["kind"] for item in conversation], ["task", "progress", "progress", "progress", "final"])
        self.assertEqual(conversation[-1]["content"], "已修复并通过测试。")


class SyntheticTrajectoryTest(unittest.TestCase):
    def setUp(self):
        self.analyzer = StageAnalyzer(relevant_files=RELEVANT_FILES, root_cause_file=ROOT_CAUSE)

    def test_minimal_success_reconstructs_all_online_stages_and_resource_metrics(self):
        read_root = 'Get-Content "Assets\\Scripts\\KitchenGameManager.cs"'
        write_root = 'Set-Content "Assets\\Scripts\\KitchenGameManager.cs"'
        validate = '& Unity.exe -runTests -testPlatform EditMode'
        records = [
            event(1, 0, "turn_start", request="repair"),
            event(2, 5, "model_usage", prompt_tokens=100, completion_tokens=20, total_tokens=120),
            event(3, 5, "model_preflight", context_usage_percent=25),
            tool_start(4, 10, read_root),
            tool_end(5, 20, read_root, output="manager", digest="manager"),
            tool_start(6, 30, write_root),
            tool_end(7, 40, write_root),
            event(8, 45, "diff_snapshot", oracle_match=True),
            tool_start(9, 50, validate),
            tool_end(10, 70, validate, output="passed", digest="passed"),
            event(11, 80, "turn_end", exit_status="Submitted", submission="fixed"),
            event(12, 100, "validation_end", validation_scope="public", status="passed"),
            event(13, 120, "validation_end", validation_scope="hidden", status="passed"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertEqual(metrics["milestones_ms"]["T3_root_cause_file"], 10)
        self.assertEqual(metrics["milestones_ms"]["T5_first_correct_patch"], 45)
        self.assertEqual(metrics["stage_duration_ms"]["public_validation"], 20)
        self.assertEqual(metrics["stage_duration_ms"]["hidden_validation"], 20)
        self.assertTrue(metrics["outcome"]["agent_submitted"])
        self.assertEqual(metrics["context"]["total_tokens"], 120)
        self.assertEqual(metrics["context"]["peak_context_usage_percent"], 25)

    def test_irrelevant_searches_quantify_poor_navigation(self):
        records = [
            event(1, 0, "turn_start", request="repair"),
            tool_start(2, 10, 'Get-Content "Assets\\Audio\\SoundManager.cs"'),
            tool_start(3, 20, 'Get-Content "Assets\\Scripts\\Player.cs"'),
            tool_start(4, 30, 'Get-Content "Assets\\Scripts\\KitchenGameManager.cs"'),
            event(5, 40, "turn_end", exit_status="Failed"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertEqual(metrics["navigation"]["root_cause_rank"], 3)
        self.assertAlmostEqual(metrics["navigation"]["navigation_precision"], 1 / 3)
        self.assertAlmostEqual(metrics["navigation"]["unrelated_file_ratio"], 2 / 3)

    def test_correct_patch_without_validation_exposes_validation_delay(self):
        write_root = 'Set-Content "Assets\\Scripts\\KitchenGameManager.cs"'
        records = [
            event(1, 0, "turn_start", request="repair"),
            tool_start(2, 10, 'Get-Content "Assets\\Scripts\\KitchenGameManager.cs"'),
            tool_end(3, 20, write_root),
            event(4, 25, "diff_snapshot", oracle_match=True),
            event(5, 100, "turn_end", exit_status="TotalTokenLimitExceeded"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertEqual(metrics["milestones_ms"]["T5_first_correct_patch"], 25)
        self.assertIsNone(metrics["milestones_ms"]["T6_first_validation"])
        self.assertFalse(metrics["outcome"]["agent_submitted"])
        self.assertGreater(metrics["stage_duration_ms"]["editing"], 0)

    def test_ui_bypass_does_not_count_as_correct_patch(self):
        bypass = 'Set-Content "Assets\\Scripts\\UI\\TutorialUI.cs"'
        records = [
            event(1, 0, "turn_start", request="repair"),
            tool_start(2, 10, bypass),
            tool_end(3, 20, bypass),
            event(4, 25, "diff_snapshot", oracle_match=False),
            event(5, 30, "turn_end", exit_status="Submitted", submission="hidden directly"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertIsNone(metrics["milestones_ms"]["T5_first_correct_patch"])
        self.assertTrue(metrics["outcome"]["agent_submitted"])

    def test_token_limit_without_submission_creates_readable_failure(self):
        records = [
            event(1, 0, "turn_start", request="repair"),
            event(2, 10, "model_usage", prompt_tokens=70000, completion_tokens=1000, total_tokens=71000),
            event(3, 20, "agent_limit_reached", limit="max_total_tokens"),
            event(4, 30, "turn_end", exit_status="TotalTokenLimitExceeded", submission=""),
        ]

        metrics = self.analyzer.analyze(records)
        conversation = project_conversation(records)

        self.assertEqual(metrics["outcome"]["exit_status"], "TotalTokenLimitExceeded")
        self.assertTrue(metrics["outcome"]["missing_final_answer"])
        self.assertEqual(conversation[-1]["kind"], "failure")
        self.assertIn("TotalTokenLimitExceeded", conversation[-1]["content"])

    def test_edit_after_validation_is_counted_as_phase_reentry(self):
        validate = "& Unity.exe -runTests"
        rewrite = 'Set-Content "Assets\\Scripts\\KitchenGameManager.cs"'
        records = [
            event(1, 0, "turn_start", request="repair"),
            tool_start(2, 10, validate),
            tool_end(3, 20, validate, returncode=1),
            tool_start(4, 30, rewrite),
            tool_end(5, 40, rewrite),
            event(6, 50, "turn_end", exit_status="Submitted", submission="fixed"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertEqual(metrics["phase_reentry"]["editing_after_validation"], 1)

    def test_duplicate_observations_are_quantified_by_raw_size(self):
        command = 'Get-Content "Assets\\Scripts\\KitchenGameManager.cs"'
        records = [
            event(1, 0, "turn_start", request="repair"),
            tool_end(2, 10, command, output="same", digest="same"),
            tool_end(3, 20, command, output="same", digest="same"),
            event(4, 30, "turn_end", exit_status="Failed"),
        ]

        metrics = self.analyzer.analyze(records)

        self.assertEqual(metrics["context"]["raw_output_chars"], 8)
        self.assertEqual(metrics["context"]["repeated_observation_ratio"], 0.5)
        self.assertEqual(metrics["behavior"]["repeated_commands"], 0)

    def test_legacy_aci_trajectory_replay_counts_two_reads_and_blocked_third(self):
        path = "Assets/Tests/PlayMode/KitchenGameManagerPlayModeTests.cs"
        action = lambda call_id: {
            "tool": "code_file_read",
            "arguments": {"path": path},
            "tool_call_id": call_id,
        }
        success_extra = {
            "returncode": 0,
            "aci": True,
            "query_tool": "code_file_read",
            "structured": {"status": "ok", "path": path},
            "node_ids": ["test-file"],
            "evidence_sources": [f"source:{path}:1-53"],
            "evidence_claim": f"Read source file {path} at SHA-256 db482e.",
            "output_chars": 100,
            "output_sha256": "db482e",
        }
        trajectory = {
            "info": {"model_stats": {"total_tokens": 3000}},
            "messages": [
                {"role": "assistant", "extra": {"actions": [action("read-1")]}},
                {"role": "tool", "content": "first", "extra": success_extra},
                {"role": "assistant", "extra": {"actions": [action("read-2")]}},
                {"role": "tool", "content": "second", "extra": success_extra},
                {"role": "assistant", "extra": {"actions": [action("read-3")]}},
                {
                    "role": "tool",
                    "content": "blocked",
                    "extra": {
                        "returncode": -2,
                        "blocked": True,
                        "guard": "repeated_action",
                    },
                },
            ],
        }

        replayed = replay_aci_tool_events(trajectory)
        metrics = self.analyzer.analyze(
            [
                event(1, 0, "turn_start", request="repair"),
                event(2, 10, "turn_end", exit_status="RepeatedActionExceeded"),
            ],
            trajectory=trajectory,
        )

        self.assertEqual(6, len(replayed))
        self.assertEqual([0, 0, -2], [
            item["returncode"] for item in replayed if item["event"] == "tool_end"
        ])
        self.assertEqual(3, metrics["research"]["tools_and_cost"]["aci_tool_calls"])
        self.assertEqual(0, metrics["behavior"]["repeated_commands"])
        self.assertEqual(1, metrics["research"]["control"]["blocked_actions"])
        self.assertAlmostEqual(
            2 / 3, metrics["research"]["control"]["duplicate_action_ratio"]
        )
        self.assertEqual(1.0, metrics["research"]["memory"]["evidence_write_recall"])
        self.assertEqual(1.0, metrics["research"]["memory"]["evidence_read_recall"])
        self.assertEqual(1, metrics["research"]["retrieval"]["distinct_paths_at_k"])
        self.assertEqual(1.0, metrics["research"]["retrieval"]["test_node_ratio_at_k"])


if __name__ == "__main__":
    unittest.main()
