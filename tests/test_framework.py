import json
import tempfile
import unittest
from pathlib import Path

from game_agent.framework.agents.default import DefaultAgent
from game_agent.framework.environments.local import LocalEnvironment
from game_agent.framework.exceptions import Submitted


class SubmitModel:
    config = {}

    def query(self, messages, **kwargs):
        return {
            "role": "assistant",
            "content": "",
            "extra": {
                "actions": [{"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"}],
                "cost": 0.25,
            },
        }

    def format_message(self, **kwargs):
        return kwargs

    def format_observation_messages(self, message, outputs, template_vars=None):
        return []

    def get_template_vars(self, **kwargs):
        return {}

    def serialize(self):
        return {"info": {"config": {"model": "fixture"}}}


class FrameworkTest(unittest.TestCase):
    def test_local_environment_executes_and_detects_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = LocalEnvironment(cwd=directory, timeout=5)

            self.assertEqual(environment.execute({"command": "echo framework-ready"})["returncode"], 0)
            with self.assertRaises(Submitted):
                environment.execute({"command": "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"})

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

            self.assertEqual(agent.run("finish")["exit_status"], "Submitted")
            saved = json.loads(trajectory.read_text(encoding="utf-8"))
            self.assertEqual(saved["info"]["framework_version"], "2.4.6-local")
            self.assertEqual(
                saved["info"]["model_stats"],
                {"instance_cost": 0.25, "api_calls": 1, "tool_calls": 1},
            )
            self.assertEqual(saved["trajectory_format"], "mini-swe-agent-1.1")


if __name__ == "__main__":
    unittest.main()
