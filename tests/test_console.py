import io
import json
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from game_agent.console import ConsoleRenderer, ConsoleSession, ConsoleTask, diff_summary


class ConversationalFixtureModel:
    def __init__(self) -> None:
        self.config = SimpleNamespace(model_name="fixture")
        self.histories: list[list[dict]] = []
        self.calls = 0

    def query(self, messages, **kwargs):
        self.histories.append(deepcopy(messages))
        self.calls += 1
        if self.calls % 2:
            command = "echo inspected"
        else:
            command = f"echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT && echo answer-{self.calls // 2}"
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": [{"command": command, "tool_call_id": f"call-{self.calls}"}],
                "cost": 0.1,
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


class ConsoleTaskTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "UnityProject"
        (self.project / "ProjectSettings").mkdir(parents=True)
        (self.project / "ProjectSettings" / "ProjectVersion.txt").write_text(
            "m_EditorVersion: test", encoding="utf-8"
        )
        subprocess.run(["git", "init"], cwd=self.project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.project, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=self.project, check=True)
        source = self.project / "source.txt"
        source.write_text("before\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.project, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=self.project, check=True, capture_output=True)

        self.config = self.root / "config.json"
        self.config.write_text(
            json.dumps(
                {
                    "experiment": {
                        "config_id": "console-test",
                        "backend": "fixture",
                        "target_project": str(self.project),
                        "tool": "bash",
                        "max_input_tokens": 1000,
                        "max_output_tokens": 1000,
                        "max_total_tokens": 2000,
                        "max_rounds": 2,
                        "cost_limit": 10,
                    },
                    "model": {"model_name": "fixture"},
                    "environment": {"cwd": str(self.project), "timeout": 5},
                    "agent": {
                        "system_template": "Work in {{ cwd }}",
                        "instance_template": "{{ task }}",
                        "step_limit": 2,
                        "cost_limit": 10,
                    },
                    "logging": {"events_path": "unused", "trajectory_path": "unused"},
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def create_task(self):
        model = ConversationalFixtureModel()
        stream = io.StringIO()
        renderer = ConsoleRenderer(stream)
        task = ConsoleTask(
            self.config,
            artifact_root=self.root / "artifacts",
            task_id="console-task",
            renderer=renderer,
            model_factory=lambda _name, _config: model,
        )
        return task, model, stream

    def test_turns_retain_context_and_reset_per_turn_limits(self):
        task, model, stream = self.create_task()

        first = task.run_turn("inspect the project")
        second = task.run_turn("continue with the previous result")
        task.close()

        self.assertEqual(first["submission"].strip(), "answer-1")
        self.assertEqual(second["submission"].strip(), "answer-2")
        self.assertEqual(task.agent.turn, 2)
        self.assertEqual(task.agent.n_calls, 4)
        second_turn_history = model.histories[2]
        self.assertEqual(
            [message["role"] for message in second_turn_history],
            ["system", "user", "assistant", "tool", "assistant", "tool", "assistant", "user"],
        )
        self.assertIn("answer-1", second_turn_history[-2]["content"])
        self.assertIn("[Agent]", stream.getvalue())
        self.assertIn("[Model]", stream.getvalue())
        self.assertIn("[Env]", stream.getvalue())
        self.assertIn("[Skill]", stream.getvalue())

    def test_events_and_artifacts_capture_component_rotation(self):
        task, _, _ = self.create_task()
        (self.project / "source.txt").write_text("after\n", encoding="utf-8")

        task.run_turn("verify events")
        task.close()

        events = [
            json.loads(line)
            for line in (task.artifact_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        names = [event["event"] for event in events]
        self.assertEqual(names.count("skill_not_found"), 1)
        self.assertLess(names.index("agent_round_start"), names.index("model_start"))
        self.assertLess(names.index("model_start"), names.index("model_end"))
        self.assertLess(names.index("model_end"), names.index("tool_start"))
        self.assertLess(names.index("tool_start"), names.index("tool_end"))
        self.assertIn("agent_observation_added", names)
        self.assertTrue(all(event["returncode"] == 0 for event in events if event["event"] == "tool_end"))
        self.assertEqual({event["task_id"] for event in events}, {"console-task"})
        for name in ("config.json", "events.jsonl", "trajectory.json", "result.json", "diff.patch"):
            self.assertTrue((task.artifact_dir / name).is_file(), name)
        result = json.loads((task.artifact_dir / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["turn_count"], 1)
        self.assertEqual(result["model_calls"], 2)
        trajectory = json.loads((task.artifact_dir / "trajectory.json").read_text(encoding="utf-8"))
        self.assertEqual(trajectory["info"]["exit_status"], "Submitted")
        self.assertEqual(trajectory["info"]["submission"].strip(), "answer-1")
        self.assertIn("+after", (task.artifact_dir / "diff.patch").read_text(encoding="utf-8"))

    def test_session_new_command_starts_an_independent_task(self):
        stream = io.StringIO()
        renderer = ConsoleRenderer(stream)
        created: list[ConsoleTask] = []

        def factory(config_path, **kwargs):
            model = ConversationalFixtureModel()
            task = ConsoleTask(
                config_path,
                project_path=kwargs["project_path"],
                artifact_root=kwargs["artifact_root"],
                task_id=f"task-{len(created) + 1}",
                renderer=kwargs["renderer"],
                model_factory=lambda _name, _config: model,
            )
            created.append(task)
            return task

        session = ConsoleSession(
            self.config,
            artifact_root=self.root / "session-artifacts",
            renderer=renderer,
            task_factory=factory,
        )
        session.handle("first task")
        session.handle("/new second task")

        self.assertEqual([task.task_id for task in created], ["task-1", "task-2"])
        self.assertTrue(created[0].closed)
        self.assertEqual(session.task.agent.turn, 1)
        current_users = [message["content"] for message in session.task.agent.messages if message["role"] == "user"]
        self.assertEqual(current_users, ["second task"])
        session.close()

    def test_diff_summary_counts_files_and_lines(self):
        summary = diff_summary(
            "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n-old\n+new\n"
        )
        self.assertEqual(summary, {"files": 1, "additions": 1, "deletions": 1})


if __name__ == "__main__":
    unittest.main()
