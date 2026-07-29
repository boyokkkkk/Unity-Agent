from __future__ import annotations

import json
import multiprocessing
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from game_agent.mini import load_config
from game_agent.registry import COMPONENTS
from game_agent.services.worker import _write_json, run_worker

from .schemas import RESULT_SCHEMA_VERSION


class UnityBenchmarkAdapter:
    """GameDevBench-style solver adapter backed by the managed Unity worker contract."""

    def run_case(self, case: dict[str, Any], attempt_dir: Path, attempt: int) -> dict[str, Any]:
        attempt_dir.mkdir(parents=True, exist_ok=False)
        config = self._build_config(case)
        input_config = attempt_dir / "input-config.json"
        _write_json(input_config, config)
        started = time.perf_counter()
        context = multiprocessing.get_context("spawn")
        worker = context.Process(
            name=f"unity-benchmark-{case['case_id']}-{attempt}",
            target=run_worker,
            args=(case["case_id"], case["task"], str(input_config), case["project_path"], str(attempt_dir)),
        )
        worker.start()
        worker.join()
        exitcode = worker.exitcode
        worker.close()
        duration = time.perf_counter() - started
        if exitcode != 0 and not (attempt_dir / "result.json").is_file():
            raise RuntimeError(f"Unity benchmark worker exited with code {exitcode}")
        raw_result = self._read_json(attempt_dir / "result.json")
        trajectory = self._read_json(attempt_dir / "trajectory.json")
        model_stats = trajectory.get("info", {}).get("model_stats", {})
        token_usage = raw_result.get("token_usage") or {
            key: model_stats.get(key, 0)
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        validation = raw_result.get("validation") or self._read_json(attempt_dir / "validation" / "summary.json")
        validation_enabled = bool(config.get("validation", {}).get("enabled", False))
        validation_status = validation.get("status", "missing" if validation_enabled else "disabled")
        agent_success = raw_result.get("exit_status") == "Submitted"
        verified_success = agent_success and validation_status == "passed"
        success = verified_success if validation_enabled else agent_success
        error = str(raw_result.get("error", ""))
        rate_limited = any(marker in error.casefold() for marker in ("rate limit", "rate_limit", "429"))
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "case_id": case["case_id"],
            "task_id": case["task_id"],
            "attempt": attempt,
            "axes": case["axes"],
            "success": success,
            "agent_success": agent_success,
            "verified_success": verified_success,
            "validation_status": validation_status,
            "exit_status": raw_result.get("exit_status", ""),
            "submission": raw_result.get("submission", ""),
            "error": error,
            "rate_limited": rate_limited,
            "duration_seconds": duration,
            "cost": float(model_stats.get("instance_cost", 0.0) or 0.0),
            "model_calls": int(model_stats.get("api_calls", 0) or 0),
            "tool_calls": int(model_stats.get("tool_calls", 0) or 0),
            "rounds": int(model_stats.get("api_calls", 0) or 0),
            "token_usage": token_usage,
            "validation": validation,
            "artifact_dir": str(attempt_dir),
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _build_config(case: dict[str, Any]) -> dict[str, Any]:
        config = deepcopy(load_config(Path(case["config_path"])))
        model = case["model"]
        config["model"].update(
            model_name=model["model_name"],
            model_class=model["model_class"],
            model_kwargs=deepcopy(model.get("model_kwargs", {})),
            cost_tracking=model.get("cost_tracking", "default"),
        )
        seed = case["seed"]
        config["experiment"]["seed"] = seed
        config["model"]["model_kwargs"].setdefault("seed", seed)
        skill = case["skill"]
        config["skills"] = {
            **config.get("skills", {}),
            "enabled": skill.get("enabled", True),
            "paths": skill.get("paths", []),
        }
        config.setdefault("workspace", {"isolation": "auto", "root": ""})
        return config


def register_builtin_adapters() -> None:
    COMPONENTS.register("benchmark_adapter", "unity", UnityBenchmarkAdapter)
