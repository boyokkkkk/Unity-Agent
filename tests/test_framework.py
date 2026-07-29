import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from game_agent.framework.agents import get_agent
from game_agent.framework.agents.default import DefaultAgent
from game_agent.framework.environments.local import LocalEnvironment
from game_agent.framework.exceptions import FormatError
from game_agent.framework.models.utils.actions_toolcall import (
    format_toolcall_observation_messages,
    parse_toolcall_actions,
)
from game_agent.mini import KitchenEnvironment


class SubmitModel:
    config = {}

    def estimate_input_tokens(self, messages):
        return 10

    def query(self, messages, **kwargs):
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": [{"tool": "submit", "answer": "finished", "tool_call_id": "submit-1"}],
                "cost": 0.25,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        }

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars=None):
        actions = message.get("extra", {}).get("actions", [])
        return [
            {
                "role": "tool",
                "content": output.get("output", ""),
                "tool_call_id": action.get("tool_call_id", ""),
            }
            for action, output in zip(actions, outputs)
        ]

    def get_template_vars(self, **kwargs):
        return {}

    def serialize(self):
        return {"info": {"config": {"model": "fixture"}}}


class FrameworkTest(unittest.TestCase):
    def test_agent_factory_preserves_runtime_objects_without_deepcopy(self):
        class Recorder:
            def emit(self, *args, **kwargs):
                return None

        with tempfile.TemporaryDirectory() as directory:
            recorder = Recorder()
            skill_runtime = SimpleNamespace(resolve=lambda _task: None)
            agent = get_agent(
                SubmitModel(),
                LocalEnvironment(cwd=directory, timeout=5),
                {
                    "system_template": "system",
                    "instance_template": "{{ task }}",
                    "event_sink": recorder.emit,
                    "skill_runtime": skill_runtime,
                },
            )

            self.assertIs(agent.event_sink.__self__, recorder)
            self.assertIs(agent.skill_runtime, skill_runtime)

    @staticmethod
    def tool_call(name, arguments, call_id="call-1"):
        return SimpleNamespace(
            id=call_id,
            function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
        )

    def test_tool_protocol_parses_powershell_and_submit(self):
        powershell = parse_toolcall_actions(
            [self.tool_call("powershell", {"command": "Get-ChildItem Assets"})],
            format_error_template="{{ error }}",
        )
        submit = parse_toolcall_actions(
            [self.tool_call("submit", {"answer": "done"})],
            format_error_template="{{ error }}",
        )

        self.assertEqual(powershell[0]["tool"], "powershell")
        self.assertEqual(powershell[0]["command"], "Get-ChildItem Assets")
        self.assertEqual(submit[0]["tool"], "submit")
        self.assertEqual(submit[0]["answer"], "done")

        with self.assertRaises(FormatError):
            parse_toolcall_actions(
                [
                    self.tool_call("powershell", {"command": "Get-Location"}, "call-1"),
                    self.tool_call("submit", {"answer": "done"}, "call-2"),
                ],
                format_error_template="{{ error }}",
            )

    def test_local_environment_executes_real_powershell_with_utf8_output(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = LocalEnvironment(cwd=directory, timeout=5)

            output = environment.execute(
                {"tool": "powershell", "command": "Write-Output framework-ready; Write-Output '框架就绪'"}
            )

            self.assertEqual(output["returncode"], 0)
            self.assertIn("framework-ready", output["output"])
            self.assertIn("框架就绪", output["output"])

    def test_large_tool_output_is_artifacted_and_observation_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = LocalEnvironment(
                cwd=directory,
                artifact_dir=directory,
                observation_max_chars=400,
                observation_max_lines=8,
                observation_head_lines=2,
                observation_tail_lines=2,
            )
            raw_output = "".join(f"line-{index:04d}-payload\n" for index in range(50))

            output = environment._finalize_output(
                {"output": raw_output, "returncode": 0, "exception_info": ""}
            )

            self.assertTrue(output["extra"]["output_truncated"])
            self.assertEqual(output["extra"]["output_lines"], 50)
            self.assertLessEqual(len(output["output"]), 400)
            self.assertLessEqual(len(output["output"].splitlines()), 8)
            self.assertIn("Output truncated: 50 lines", output["output"])
            self.assertIn("line-0000", output["output"])
            self.assertIn("line-0049", output["output"])
            artifact = root / output["extra"]["artifact_path"]
            self.assertEqual(artifact.read_text(encoding="utf-8"), raw_output)

            observations = format_toolcall_observation_messages(
                actions=[{"command": "large", "tool_call_id": "call-1"}],
                outputs=[output],
                observation_template="{{ output.output }}",
            )
            self.assertNotIn("raw_output", observations[0]["extra"])
            self.assertEqual(observations[0]["extra"]["artifact_path"], output["extra"]["artifact_path"])

    def test_kitchen_environment_blocks_unscoped_unity_searches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings" / "ProjectVersion.txt").write_text("test", encoding="utf-8")
            (root / "Assets").mkdir()
            environment = KitchenEnvironment(
                cwd=directory,
                telemetry_path=str(root / "events.jsonl"),
                run_id="scope-test",
                config_id="scope-test",
            )

            blocked = environment.execute({"command": "dir /s /b *.cs"})

            self.assertEqual(blocked["returncode"], -2)
            self.assertTrue(blocked["extra"]["blocked"])
            self.assertIn("do not recursively search the project root", blocked["exception_info"])
            self.assertEqual(environment._validate_command("dir /s /b Assets\\*.cs", directory), "")
            self.assertIn(
                "generated directories",
                environment._validate_command("Get-ChildItem Library -Recurse", directory),
            )

    def test_kitchen_tool_event_contains_preview_not_full_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ProjectSettings").mkdir()
            (root / "ProjectSettings" / "ProjectVersion.txt").write_text("test", encoding="utf-8")
            events_path = root / "events.jsonl"
            environment = KitchenEnvironment(
                cwd=directory,
                telemetry_path=str(events_path),
                run_id="artifact-test",
                config_id="artifact-test",
                observation_max_chars=400,
                observation_max_lines=8,
                observation_head_lines=2,
                observation_tail_lines=2,
            )
            command = (
                f'& "{sys.executable}" -c "print(chr(10).join('
                "'line-%04d-payload'%i for i in range(50)))\""
            )

            output = environment.execute({"command": command})
            records = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            tool_end = next(record for record in records if record["event"] == "tool_end")

            self.assertEqual(output["returncode"], 0)
            self.assertTrue(tool_end["output_truncated"])
            self.assertEqual(tool_end["output"], output["output"])
            self.assertLessEqual(len(tool_end["output"]), 400)
            artifact = root / tool_end["artifact_path"]
            self.assertIn("line-0025-payload", artifact.read_text(encoding="utf-8"))

    def test_default_agent_runs_and_saves_trajectory(self):
        with tempfile.TemporaryDirectory() as directory:
            trajectory = Path(directory) / "trajectory.json"
            agent = DefaultAgent(
                SubmitModel(),
                LocalEnvironment(cwd=directory, timeout=5),
                system_template="Work in {{ cwd }}",
                instance_template="{{ task }}",
                step_limit=2,
                output_path=trajectory,
            )

            result = agent.run("finish")

            self.assertEqual(result["exit_status"], "Submitted")
            self.assertEqual(result["submission"], "finished")
            self.assertTrue(any(message.get("role") == "tool" for message in agent.messages))
            saved = json.loads(trajectory.read_text(encoding="utf-8"))
            self.assertEqual(saved["info"]["framework_version"], "2.4.6-local")
            self.assertEqual(
                saved["info"]["model_stats"],
                {
                    "instance_cost": 0.25,
                    "api_calls": 1,
                    "tool_calls": 1,
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                    "last_input_tokens": 10,
                    "max_input_tokens": 0,
                    "max_total_tokens": 0,
                },
            )
            self.assertEqual(saved["trajectory_format"], "mini-swe-agent-1.1")

    def test_input_token_limit_stops_before_model_call(self):
        class OversizedModel(SubmitModel):
            calls = 0

            def estimate_input_tokens(self, messages):
                return 101

            def query(self, messages, **kwargs):
                self.calls += 1
                return super().query(messages, **kwargs)

        with tempfile.TemporaryDirectory() as directory:
            model = OversizedModel()
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, timeout=5),
                system_template="system",
                instance_template="{{ task }}",
                step_limit=5,
                max_input_tokens=100,
                max_output_tokens=20,
                max_total_tokens=1000,
            )

            result = agent.run("too large")

            self.assertEqual(result["exit_status"], "InputTokenLimitExceeded")
            self.assertEqual(model.calls, 0)
            self.assertEqual(agent.n_calls, 0)
            self.assertEqual(agent.total_tokens, 0)

    def test_total_token_limit_stops_before_second_model_call(self):
        class ContinuingModel(SubmitModel):
            def __init__(self):
                self.calls = 0
                self.max_tokens = []

            def query(self, messages, **kwargs):
                self.calls += 1
                self.max_tokens.append(kwargs.get("max_tokens"))
                return {
                    "role": "assistant",
                    "content": "",
                    "extra": {
                        "actions": [{"tool": "powershell", "command": "Write-Output keep-going"}],
                        "cost": 0.1,
                        "prompt_tokens": 20,
                        "completion_tokens": 5,
                        "total_tokens": 25,
                    },
                }

        with tempfile.TemporaryDirectory() as directory:
            model = ContinuingModel()
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, timeout=5),
                system_template="system",
                instance_template="{{ task }}",
                step_limit=5,
                max_input_tokens=100,
                max_output_tokens=20,
                max_total_tokens=25,
            )

            result = agent.run("continue")

            self.assertEqual(result["exit_status"], "TotalTokenLimitExceeded")
            self.assertEqual(model.calls, 1)
            self.assertEqual(agent.n_calls, 1)
            self.assertEqual(agent.n_tool_calls, 0)
            self.assertEqual(agent.total_tokens, 25)
            self.assertEqual(model.max_tokens, [15])

    def test_third_identical_action_is_blocked_before_environment_execution(self):
        class RepeatingModel(SubmitModel):
            def __init__(self):
                self.calls = 0

            def query(self, messages, **kwargs):
                self.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "extra": {
                        "actions": [
                            {
                                "tool": "powershell",
                                "command": "Write-Output same-result",
                                "tool_call_id": f"repeat-{self.calls}",
                            }
                        ],
                        "cost": 0.1,
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }

        with tempfile.TemporaryDirectory() as directory:
            model = RepeatingModel()
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, artifact_dir=directory, timeout=5),
                system_template="system",
                instance_template="{{ task }}",
                step_limit=10,
                max_repeated_actions=2,
                max_no_progress_rounds=10,
            )

            result = agent.run("repeat")

            self.assertEqual(result["exit_status"], "RepeatedActionExceeded")
            self.assertEqual(model.calls, 3)
            self.assertEqual(len(list((Path(directory) / "tool-outputs").glob("*.txt"))), 2)
            self.assertTrue(any(message.get("extra", {}).get("agent_progress_warning") for message in agent.messages))

    def test_two_no_progress_rounds_stop_different_actions_with_same_result(self):
        class NoProgressModel(SubmitModel):
            def __init__(self):
                self.calls = 0

            def query(self, messages, **kwargs):
                self.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "extra": {
                        "actions": [
                            {
                                "tool": "powershell",
                                "command": f"Write-Output unchanged # attempt-{self.calls}",
                                "tool_call_id": f"progress-{self.calls}",
                            }
                        ],
                        "cost": 0.1,
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }

        with tempfile.TemporaryDirectory() as directory:
            model = NoProgressModel()
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, timeout=5),
                system_template="system",
                instance_template="{{ task }}",
                step_limit=10,
                max_repeated_actions=2,
                max_no_progress_rounds=2,
            )

            result = agent.run("no progress")

            self.assertEqual(result["exit_status"], "NoProgressExceeded")
            self.assertEqual(model.calls, 3)
            self.assertEqual(agent.no_progress_rounds, 2)

    def test_three_consecutive_tool_failures_stop_agent(self):
        class FailingModel(SubmitModel):
            def __init__(self):
                self.calls = 0

            def query(self, messages, **kwargs):
                self.calls += 1
                return {
                    "role": "assistant",
                    "content": "",
                    "extra": {
                        "actions": [
                            {
                                "tool": "powershell",
                                "command": f"Write-Output failed; exit 1 # attempt-{self.calls}",
                                "tool_call_id": f"failure-{self.calls}",
                            }
                        ],
                        "cost": 0.1,
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }

        with tempfile.TemporaryDirectory() as directory:
            model = FailingModel()
            agent = DefaultAgent(
                model,
                LocalEnvironment(cwd=directory, timeout=5),
                system_template="system",
                instance_template="{{ task }}",
                step_limit=10,
                max_no_progress_rounds=0,
                max_consecutive_tool_failures=3,
            )

            result = agent.run("fail")

            self.assertEqual(result["exit_status"], "ConsecutiveToolFailuresExceeded")
            self.assertEqual(model.calls, 3)
            self.assertEqual(agent.consecutive_tool_failures, 3)


if __name__ == "__main__":
    unittest.main()
