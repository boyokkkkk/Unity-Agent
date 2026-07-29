from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from game_agent.benchmark.runner import BenchmarkRunner, aggregate_results
from game_agent.benchmark.schemas import BenchmarkManifest, RESULT_SCHEMA_VERSION
from game_agent.framework.models import get_model
from game_agent.framework.models.litellm_response_model import LitellmResponseModel
from game_agent.framework.models.openrouter_model import OpenRouterModel
from game_agent.framework.models.openrouter_response_model import OpenRouterResponseModel
from game_agent.framework.models.utils.actions_toolcall_response import (
    RESPONSE_TOOLS,
    format_response_observations,
    parse_response_actions,
)
from game_agent.registry import COMPONENTS, ComponentRegistry


class FakeResponse:
    def __init__(self, output: list[dict]):
        self.output = output
        self.status = "completed"
        self.usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

    def model_dump(self, mode=None) -> dict:
        return {
            "object": "response", "status": self.status, "output": self.output, "usage": self.usage
        }


class RegistryAndModelTest(unittest.TestCase):
    def test_controlled_registry_rejects_unknown_dynamic_paths_and_duplicates(self):
        registry = ComponentRegistry()
        factory = lambda: "ok"
        registry.register("model", "fixture", factory)

        self.assertEqual(registry.create("model", "fixture"), "ok")
        with self.assertRaises(ValueError):
            registry.resolve("model", "package.module.Class")
        with self.assertRaises(ValueError):
            registry.register("model", "fixture", lambda: "different")
        with self.assertRaises(ValueError):
            registry.register("arbitrary", "fixture", factory)

    def test_model_factory_exposes_only_registered_variants(self):
        self.assertEqual(type(get_model("test/model", {"model_class": "responses"})).__name__, "LitellmResponseModel")
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fixture"}):
            self.assertEqual(type(get_model("test/model", {"model_class": "openrouter"})).__name__, "OpenRouterModel")
            self.assertEqual(
                type(get_model("test/model", {"model_class": "openrouter_response"})).__name__,
                "OpenRouterResponseModel",
            )
        with self.assertRaises(ValueError):
            get_model("test/model", {"model_class": "some.module.ArbitraryModel"})

    def test_responses_protocol_parses_powershell_submit_and_observation(self):
        powershell = parse_response_actions(
            [{"type": "function_call", "call_id": "call-1", "name": "powershell", "arguments": '{"command":"Get-Location"}'}],
            format_error_template="{{ error }}",
        )
        submit = parse_response_actions(
            [{"type": "function_call", "call_id": "call-2", "name": "submit", "arguments": '{"answer":"done"}'}],
            format_error_template="{{ error }}",
        )
        observations = format_response_observations(
            actions=powershell,
            outputs=[{"output": "ok", "returncode": 0, "exception_info": ""}],
            observation_template="{{ output.output }}",
        )

        self.assertEqual([tool["name"] for tool in RESPONSE_TOOLS], ["powershell", "submit"])
        self.assertEqual(powershell[0]["tool"], "powershell")
        self.assertEqual(submit[0]["tool"], "submit")
        self.assertEqual(observations[0]["type"], "function_call_output")
        self.assertEqual(observations[0]["call_id"], "call-1")

    def test_litellm_responses_model_persists_actions_usage_and_cost(self):
        model = LitellmResponseModel(model_name="test/model", cost_tracking="ignore_errors")
        response = FakeResponse(
            [{"type": "function_call", "call_id": "call-1", "name": "powershell", "arguments": '{"command":"Get-Location"}'}]
        )
        with patch.object(model, "_query", return_value=response), patch.object(
            model, "_calculate_cost", return_value={"cost": 0.25}
        ):
            message = model.query([model.format_message(role="user", content="inspect")])

        self.assertEqual(message["object"], "response")
        self.assertEqual(message["extra"]["actions"][0]["command"], "Get-Location")
        self.assertEqual(message["extra"]["total_tokens"], 15)
        self.assertEqual(message["extra"]["cost"], 0.25)

    def test_openrouter_chat_and_response_payloads_use_correct_endpoints(self):
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "fixture"}):
            chat = OpenRouterModel(model_name="provider/model", cost_tracking="ignore_errors")
            response_model = OpenRouterResponseModel(model_name="provider/model", cost_tracking="ignore_errors")
        with patch.object(chat, "_post", return_value={}) as post:
            chat._query([{"role": "user", "content": "hi"}], max_tokens=20)
        chat_payload = post.call_args.args[0]
        with patch.object(response_model, "_post", return_value={}) as post:
            response_model._query([{"type": "message", "role": "user", "content": []}], max_tokens=20)
        response_payload = post.call_args.args[0]

        self.assertIn("messages", chat_payload)
        self.assertEqual(chat_payload["tools"], __import__(
            "game_agent.framework.models.utils.actions_toolcall", fromlist=["AGENT_TOOLS"]
        ).AGENT_TOOLS)
        self.assertIn("input", response_payload)
        self.assertEqual(response_payload["max_output_tokens"], 20)
        self.assertNotIn("max_tokens", response_payload)
        with patch.object(response_model, "_estimate", side_effect=[5, 7]) as estimate:
            self.assertEqual(response_model.estimate_input_tokens([]), 12)
        self.assertEqual(estimate.call_args_list[1].args[0], RESPONSE_TOOLS)


class FixtureBenchmarkAdapter:
    calls: list[tuple[str, int]] = []

    def run_case(self, case: dict, attempt_dir: Path, attempt: int) -> dict:
        attempt_dir.mkdir(parents=True, exist_ok=False)
        self.__class__.calls.append((case["case_id"], attempt))
        success = attempt >= 2
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "case_id": case["case_id"], "task_id": case["task_id"], "attempt": attempt,
            "axes": case["axes"], "success": success, "agent_success": success,
            "verified_success": success, "validation_status": "passed" if success else "failed",
            "exit_status": "Submitted" if success else "ValidationFailed", "submission": "done" if success else "",
            "error": "" if success else "fixture failure", "rate_limited": False,
            "duration_seconds": 2.0, "cost": 0.5, "model_calls": 3, "tool_calls": 2,
            "rounds": 3, "token_usage": {"total_tokens": 100}, "validation": {},
            "artifact_dir": str(attempt_dir),
        }


class BenchmarkRunnerTest(unittest.TestCase):
    def setUp(self):
        FixtureBenchmarkAdapter.calls = []
        COMPONENTS.register("benchmark_adapter", "fixture", FixtureBenchmarkAdapter, replace=True)

    def manifest(self, root: Path) -> tuple[Path, BenchmarkManifest]:
        project = root / "project"
        project.mkdir()
        config = root / "config.json"
        config.write_text("{}", encoding="utf-8")
        data = {
            "schema_version": "game-agent-benchmark-v1",
            "benchmark_id": "matrix-test",
            "adapter": "fixture",
            "output_dir": "outputs",
            "tasks": [
                {"id": "task-1", "task": "fix it", "project_path": "project", "config_path": "config.json"}
            ],
            "matrix": {
                "models": [
                    {"name": "chat", "model_name": "test/chat", "model_class": "litellm"},
                    {"name": "responses", "model_name": "test/response", "model_class": "responses"},
                ],
                "skills": [
                    {"name": "off", "enabled": False},
                    {"name": "on", "enabled": True, "paths": []},
                ],
                "seeds": [1, 2],
            },
            "execution": {"max_workers": 3, "retries": 1, "resume": True},
        }
        path = root / "manifest.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path, BenchmarkManifest.model_validate(data)

    def test_matrix_retry_progress_resume_and_aggregation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, manifest = self.manifest(root)
            runner = BenchmarkRunner(manifest, path)

            self.assertEqual(len(runner.expand_cases()), 8)
            self.assertEqual(len({case["case_id"] for case in runner.expand_cases()}), 8)
            first = runner.run()
            calls_after_first = len(FixtureBenchmarkAdapter.calls)
            second = BenchmarkRunner(manifest, path).run()
            changed = manifest.model_copy(deep=True)
            changed.matrix.models[0].model_kwargs["temperature"] = 0.5
            changed_ids = {case["case_id"] for case in BenchmarkRunner(changed, path).expand_cases()}
            original_ids = {case["case_id"] for case in runner.expand_cases()}
            third = BenchmarkRunner(manifest, path).run(resume=False)

            self.assertEqual(first["metrics"]["overall"]["success_rate"], 1.0)
            self.assertEqual(first["metrics"]["overall"]["cost"]["total"], 8.0)
            self.assertEqual(len(first["metrics"]["by_model"]), 2)
            self.assertEqual(len(first["metrics"]["by_skill"]), 2)
            self.assertEqual(len(first["metrics"]["by_seed"]), 2)
            self.assertEqual(calls_after_first, 16)
            self.assertEqual(len(FixtureBenchmarkAdapter.calls), calls_after_first + 8)
            self.assertEqual(second["completed_cases"], 8)
            self.assertEqual(third["completed_cases"], 8)
            self.assertNotEqual(changed_ids, original_ids)
            self.assertTrue(runner.progress_path.is_file())
            self.assertTrue((runner.output_dir / "results.json").is_file())
            self.assertTrue((runner.output_dir / "summary.json").is_file())
            self.assertTrue((runner.output_dir / "results.csv").is_file())

    def test_aggregate_reports_agent_and_validation_success_separately(self):
        results = [
            {
                "axes": {"model": "m", "skill": "s", "seed": 1},
                "success": False, "agent_success": True, "verified_success": False,
                "validation_status": "skipped_unavailable", "cost": 1, "model_calls": 2,
                "rounds": 2, "duration_seconds": 4, "token_usage": {"total_tokens": 10},
            },
            {
                "axes": {"model": "m", "skill": "s", "seed": 2},
                "success": True, "agent_success": True, "verified_success": True,
                "validation_status": "passed", "cost": 3, "model_calls": 4,
                "rounds": 4, "duration_seconds": 6, "token_usage": {"total_tokens": 30},
            },
        ]
        overall = aggregate_results(results)["overall"]

        self.assertEqual(overall["success_rate"], 0.5)
        self.assertEqual(overall["agent_success_rate"], 1.0)
        self.assertEqual(overall["verified_success_rate"], 0.5)
        self.assertEqual(overall["validation"], {"skipped_unavailable": 1, "passed": 1})
        self.assertEqual(overall["cost"], {"total": 4.0, "mean": 2.0})


if __name__ == "__main__":
    unittest.main()
