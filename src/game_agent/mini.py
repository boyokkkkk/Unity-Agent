"""mini-SWE-agent compatible runner for the Kitchen Chaos Unity project.

The project-owned framework provides the reasoning loop, model adapter, format-error recovery, limits, and trajectory serialization. This module binds that framework to the selected Unity project and adds stable experiment telemetry.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from game_agent.framework.agents import get_agent
from game_agent.framework.environments import LocalEnvironment
from game_agent.framework.exceptions import Submitted
from game_agent.framework.models import get_model

from .logging import ExperimentLogger


class KitchenEnvironment(LocalEnvironment):
    """LocalEnvironment with project identity and append-only telemetry."""

    def __init__(
        self,
        *,
        telemetry_path: str,
        run_id: str,
        config_id: str,
        logger: ExperimentLogger | None = None,
        **kwargs: Any,
    ) -> None:
        project_root = Path(kwargs.get("cwd", "")).resolve()
        if not project_root.is_dir():
            raise FileNotFoundError(f"Kitchen Chaos project does not exist: {project_root}")
        if not (project_root / "ProjectSettings" / "ProjectVersion.txt").is_file():
            raise ValueError(f"Not a Unity project (ProjectVersion.txt missing): {project_root}")
        super().__init__(**kwargs)
        self.telemetry_path = Path(telemetry_path)
        self.logger = logger or ExperimentLogger(self.telemetry_path, run_id=run_id, config_id=config_id)

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        if set(action) - {"command", "tool_call_id"} or not isinstance(action.get("command"), str):
            return {
                "output": "",
                "returncode": -1,
                "exception_info": "Only the fixed mini-SWE-agent bash tool is permitted.",
            }
        command = action.get("command", "")
        self.logger.emit("tool_start", tool="bash", command=command, cwd=cwd or self.config.cwd)
        output: dict[str, Any] = {"returncode": -1, "output": "", "exception_info": ""}
        started = time.perf_counter()
        try:
            output = super().execute(action, cwd=cwd, timeout=timeout)
            return output
        except Submitted as submitted:
            output = getattr(submitted, "tool_output", output)
            raise
        finally:
            self.logger.emit(
                "tool_end",
                tool="bash",
                command=command,
                returncode=output.get("returncode"),
                output=output.get("output", ""),
                exception_info=output.get("exception_info", ""),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )

    def serialize(self) -> dict:
        data = super().serialize()
        data["info"]["config"]["kitchen_project"] = self.config.cwd
        data["info"]["config"]["telemetry_path"] = str(self.telemetry_path)
        return data


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {"experiment", "model", "environment", "agent", "logging"}
    missing = required - set(config)
    if missing:
        raise ValueError(f"Missing configuration sections: {sorted(missing)}")
    experiment = config["experiment"]
    fixed = {
        "backend", "config_id", "tool", "max_input_tokens", "max_output_tokens",
        "max_total_tokens", "max_rounds", "cost_limit",
    }
    missing_fixed = fixed - set(experiment)
    if missing_fixed:
        raise ValueError(f"Missing fixed experiment controls: {sorted(missing_fixed)}")
    if experiment["tool"] != "bash":
        raise ValueError("Week 1 baseline only permits mini-SWE-agent's bash tool")
    if config["agent"]["step_limit"] != experiment["max_rounds"]:
        raise ValueError("agent.step_limit must equal experiment.max_rounds")
    if config["agent"]["cost_limit"] != experiment["cost_limit"]:
        raise ValueError("agent.cost_limit must equal experiment.cost_limit")
    return config


def run(task: str, config_path: Path, *, run_id: str | None = None) -> dict:
    config = load_config(config_path)
    experiment = config["experiment"]
    run_id = run_id or uuid.uuid4().hex[:12]
    telemetry = Path(config["logging"]["events_path"])
    logger = ExperimentLogger(telemetry, run_id=run_id, config_id=experiment["config_id"])
    logger.emit(
        "run_start",
        backend=experiment["backend"],
        target_project=experiment["target_project"],
        tool=experiment["tool"],
        model=config["model"]["model_name"],
        max_input_tokens=experiment["max_input_tokens"],
        max_output_tokens=experiment["max_output_tokens"],
        max_total_tokens=experiment["max_total_tokens"],
        max_rounds=experiment["max_rounds"],
        task=task,
    )

    model_config = dict(config["model"])
    model_name = model_config.pop("model_name")
    model = get_model(model_name, model_config)

    environment_config = dict(config["environment"])
    environment_config.update(
        telemetry_path=str(telemetry),
        run_id=run_id,
        config_id=experiment["config_id"],
        logger=logger,
    )
    environment = KitchenEnvironment(**environment_config)

    agent_config = dict(config["agent"])
    agent_config["output_path"] = Path(config["logging"]["trajectory_path"])
    agent_config["event_sink"] = logger.emit
    agent_config["event_context_sink"] = logger.set_context
    agent = get_agent(model, environment, agent_config, default_type="default")
    try:
        result = agent.run(task)
        agent.save(
            Path(config["logging"]["trajectory_path"]),
            {"info": {"experiment": experiment, "run_id": run_id, "task": task}},
        )
        logger.emit(
            "run_end",
            exit_status=result.get("exit_status", ""),
            submission=result.get("submission", ""),
            model_calls=getattr(agent, "n_calls", None),
            model_cost=getattr(agent, "cost", None),
            trajectory_path=config["logging"]["trajectory_path"],
        )
        return result
    except Exception as exc:
        logger.emit("run_end", exit_status="exception", exception_type=type(exc).__name__, exception=str(exc))
        raise
