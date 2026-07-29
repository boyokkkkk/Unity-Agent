from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


REFERENCE_SRC = Path(__file__).resolve().parents[2] / "references" / "mini-SWE-agent" / "src"
os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
sys.path.insert(0, str(REFERENCE_SRC))

from minisweagent.agents.default import DefaultAgent as UpstreamAgent  # noqa: E402
from minisweagent.exceptions import FormatError as UpstreamFormatError  # noqa: E402

from game_agent.framework.agents.default import DefaultAgent as LocalAgent  # noqa: E402
from game_agent.framework.exceptions import FormatError as LocalFormatError  # noqa: E402


class DeterministicEnvironment:
    def execute(self, action: dict, cwd: str = "") -> dict:
        return {"output": f"observed:{action['command']}", "returncode": 0, "exception_info": ""}

    def get_template_vars(self, **kwargs) -> dict:
        return kwargs

    def serialize(self) -> dict:
        return {"info": {"config": {"environment": {}, "environment_type": "parity"}}}


class DeterministicModel:
    def __init__(self, outputs: list[dict] | None = None, *, error_type: type[Exception] | None = None):
        self.outputs = list(outputs or [])
        self.error_type = error_type
        self.calls = 0

    def query(self, messages: list[dict], **kwargs) -> dict:
        self.calls += 1
        if self.error_type:
            raise self.error_type(
                {"role": "user", "content": "bad format", "extra": {"interrupt_type": "FormatError"}}
            )
        return self.outputs.pop(0)

    def format_message(self, **kwargs) -> dict:
        return dict(kwargs)

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return [
            {
                "role": "tool",
                "tool_call_id": action.get("tool_call_id", ""),
                "content": output["output"],
                "extra": {"returncode": output["returncode"], "exception_info": output["exception_info"]},
            }
            for action, output in zip(message.get("extra", {}).get("actions", []), outputs)
        ]

    def get_template_vars(self, **kwargs) -> dict:
        return kwargs

    def serialize(self) -> dict:
        return {"info": {"config": {"model": {}, "model_type": "parity"}}}


def output(content: str, command: str, *, cost: float = 0.25) -> dict:
    return {
        "role": "assistant",
        "content": content,
        "extra": {
            "actions": [{"command": command, "tool_call_id": f"call-{command}"}],
            "cost": cost,
        },
    }


def normalize_messages(messages: list[dict]) -> list[dict]:
    normalized = []
    for message in messages:
        extra = message.get("extra", {})
        normalized.append(
            {
                "role": message.get("role", ""),
                "content": message.get("content", ""),
                "tool_call_id": message.get("tool_call_id", ""),
                "actions": [
                    {key: action.get(key, "") for key in ("command", "tool_call_id")}
                    for action in extra.get("actions", [])
                ],
                "exit_status": extra.get("exit_status", ""),
            }
        )
    return normalized


class CoreParityTest(unittest.TestCase):
    config = {
        "system_template": "system",
        "instance_template": "task={{ task }}",
        "step_limit": 1,
        "cost_limit": 3.0,
        "wall_time_limit_seconds": 0,
        "max_consecutive_format_errors": 2,
    }

    def agents(self, outputs: list[dict]):
        return (
            UpstreamAgent(DeterministicModel(outputs), DeterministicEnvironment(), **self.config),
            LocalAgent(DeterministicModel(outputs), DeterministicEnvironment(), **self.config),
        )

    def test_message_order_and_step_limit_match_upstream(self):
        upstream, local = self.agents([output("inspect", "one"), output("unused", "two")])

        upstream_result = upstream.run("fixture")
        local_result = local.run("fixture")

        self.assertEqual(upstream_result["exit_status"], "LimitsExceeded")
        self.assertEqual(local_result["exit_status"], upstream_result["exit_status"])
        self.assertEqual(normalize_messages(local.messages), normalize_messages(upstream.messages))

    def test_cost_boundary_matches_upstream(self):
        config = {**self.config, "step_limit": 0, "cost_limit": 0.5}
        outputs = [output("first", "one", cost=0.5), output("unused", "two")]
        upstream = UpstreamAgent(DeterministicModel(outputs), DeterministicEnvironment(), **config)
        local = LocalAgent(DeterministicModel(outputs), DeterministicEnvironment(), **config)

        self.assertEqual(local.run("fixture")["exit_status"], upstream.run("fixture")["exit_status"])
        self.assertEqual(local.n_calls, upstream.n_calls)
        self.assertEqual(local.cost, upstream.cost)

    def test_repeated_format_error_exit_matches_upstream(self):
        upstream = UpstreamAgent(
            DeterministicModel(error_type=UpstreamFormatError), DeterministicEnvironment(), **self.config
        )
        local = LocalAgent(
            DeterministicModel(error_type=LocalFormatError), DeterministicEnvironment(), **self.config
        )

        self.assertEqual(local.run("fixture")["exit_status"], upstream.run("fixture")["exit_status"])
        self.assertEqual(
            [item["role"] for item in normalize_messages(local.messages)],
            [item["role"] for item in normalize_messages(upstream.messages)],
        )

    def test_common_trajectory_fields_match_upstream(self):
        upstream, local = self.agents([output("inspect", "one")])
        upstream.run("fixture")
        local.run("fixture")
        upstream_data = upstream.serialize()
        local_data = local.serialize()

        self.assertEqual(local_data["schema_version"], "game-agent-trajectory-v1")
        self.assertEqual(local_data["trajectory_format"], upstream_data["trajectory_format"])
        self.assertEqual(local_data["info"]["exit_status"], upstream_data["info"]["exit_status"])
        self.assertEqual(local_data["info"]["submission"], upstream_data["info"]["submission"])
        self.assertEqual(normalize_messages(local_data["messages"]), normalize_messages(upstream_data["messages"]))


if __name__ == "__main__":
    unittest.main()
