"""mini-SWE-agent compatible runner for the Kitchen Chaos Unity project.

The project-owned framework provides the reasoning loop, model adapter, format-error recovery, limits, and trajectory serialization. This module binds that framework to the selected Unity project and adds stable experiment telemetry.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from game_agent_try.framework.agents import get_agent
from game_agent_try.framework.environments import LocalEnvironment
from game_agent_try.framework.models import get_model

from .logging import ExperimentLogger
from .baseline import enrich_tool_event
from .skills import build_skill_runtime
from .validation import UnityValidator


class KitchenEnvironment(LocalEnvironment):
    """LocalEnvironment with project identity and append-only telemetry."""

    UNITY_EXCLUDED_DIRS = {".git", "library", "temp", "logs", "obj", "build", "builds", "usersettings"}
    _RECURSIVE_SEARCH_PATTERNS = (
        r"\bdir\b[^\r\n|&]*/s\b",
        r"\bget-childitem\b[^\r\n|&]*-recurse\b",
        r"\bgci\b[^\r\n|&]*-recurse\b",
        r"\bls\b[^\r\n|&]*-[a-z]*r[a-z]*\b",
        r"\bfind(?:\.exe)?\s+",
        r"\bfindstr\b[^\r\n|&]*/s\b",
        r"\bwhere\b[^\r\n|&]*/r\b",
        r"\bgrep\b[^\r\n|&]*-[a-z]*r[a-z]*\b",
        r"\brg(?:\.exe)?\b",
    )

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
        self.telemetry_path = Path(telemetry_path)
        kwargs.setdefault("artifact_dir", str(self.telemetry_path.parent))
        super().__init__(**kwargs)
        self.logger = logger or ExperimentLogger(self.telemetry_path, run_id=run_id, config_id=config_id)

    def _validate_command(self, command: str, cwd: str) -> str:
        normalized = command.casefold()
        if not any(re.search(pattern, normalized) for pattern in self._RECURSIVE_SEARCH_PATTERNS):
            return ""

        project_root = Path(self.config.cwd).resolve()
        effective_cwd = Path(cwd).resolve()
        try:
            relative_parts = tuple(part.casefold() for part in effective_cwd.relative_to(project_root).parts)
        except ValueError:
            relative_parts = ()

        excluded_pattern = r"(?:^|[\\/\s\"'=])(" + "|".join(
            re.escape(name) for name in sorted(self.UNITY_EXCLUDED_DIRS)
        ) + r")(?:[\\/\s\"'*]|$)"
        if any(part in self.UNITY_EXCLUDED_DIRS for part in relative_parts) or re.search(
            excluded_pattern, normalized
        ):
            return (
                "Unity search scope blocked: recursive searches may not traverse generated directories "
                "Library, Temp, Logs, obj, .git, Build, Builds, or UserSettings."
            )

        scoped_cwd = bool(relative_parts and relative_parts[0] in {"assets", "packages"})
        scoped_command = bool(
            re.search(r"(?:^|[\s\"'=])[.\\/]*(assets|packages)(?:[\\/\s\"'*]|$)", normalized)
        )
        if effective_cwd == project_root and not scoped_command:
            return (
                "Unity search scope blocked: do not recursively search the project root. "
                "Search Assets or Packages explicitly, for example: dir /s /b Assets\\*.cs or "
                "Get-ChildItem Assets -Recurse -Filter *.cs. Generated directories are excluded by default."
            )
        if not scoped_cwd and not scoped_command:
            return "Unity search scope blocked: recursive searches must be limited to Assets or Packages."
        return ""

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        if (
            set(action) - {"tool", "command", "tool_call_id"}
            or action.get("tool", "powershell") != "powershell"
            or not isinstance(action.get("command"), str)
        ):
            return {
                "output": "",
                "returncode": -1,
                "exception_info": "Only the powershell execution tool is accepted by the environment.",
            }
        command = action.get("command", "")
        event_details = enrich_tool_event(command)
        self.logger.emit(
            "tool_start",
            component="environment",
            tool="powershell",
            command=command,
            cwd=cwd or self.config.cwd,
            **event_details,
        )
        output: dict[str, Any] = {"returncode": -1, "output": "", "exception_info": ""}
        started = time.perf_counter()
        try:
            output = super().execute(action, cwd=cwd, timeout=timeout)
            return output
        finally:
            self.logger.emit(
                "tool_end",
                component="environment",
                tool="powershell",
                command=command,
                returncode=output.get("returncode"),
                output=output.get("output", ""),
                exception_info=output.get("exception_info", ""),
                duration_ms=int((time.perf_counter() - started) * 1000),
                **enrich_tool_event(command, output),
                **output.get("extra", {}),
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
    if experiment["tool"] != "powershell":
        raise ValueError("The baseline requires the Windows PowerShell tool contract")
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
    logger.emit("task_start", component="run", task=task)
    logger.emit("turn_start", component="run", request=task, turn=1)

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
    agent_config["skill_runtime"] = build_skill_runtime(config, logger, config_path=config_path)
    context_config = dict(config.get("context", {}))
    configured_graph = str(context_config.get("graph_path", "")).strip()
    if configured_graph and not Path(configured_graph).is_absolute():
        context_config["graph_path"] = str((config_path.resolve().parent.parent / configured_graph).resolve())
    agent_config["context"] = context_config
    aci_config = dict(config.get("aci", {}))
    if not aci_config.get("editor_path"):
        aci_config["editor_path"] = str(config.get("validation", {}).get("editor_path", ""))
    agent_config["aci"] = aci_config
    agent_config.update(
        max_input_tokens=experiment["max_input_tokens"],
        max_output_tokens=experiment["max_output_tokens"],
        max_total_tokens=experiment["max_total_tokens"],
    )
    agent = get_agent(model, environment, agent_config, default_type="default")
    try:
        result = agent.run(task)
        result = {**result, 'token_usage': agent.token_usage()}
        validation_config = dict(config.get("validation", {}))
        if validation_config.get("enabled", False):
            validation = UnityValidator(
                Path(config["environment"]["cwd"]),
                Path(config["logging"]["trajectory_path"]).parent / "validation",
                validation_config,
                event_sink=logger.emit,
            ).run()
            result["validation"] = validation
            if validation["status"] == "failed":
                result["exit_status"] = "ValidationFailed"
        agent.last_result = dict(result)
        trajectory_extensions = {
            "info": {"experiment": experiment, "run_id": run_id, "task": task}
        }
        if "validation" in result:
            trajectory_extensions["validation"] = result["validation"]
        agent.save(
            Path(config["logging"]["trajectory_path"]),
            trajectory_extensions,
        )
        logger.emit(
            "turn_end",
            component="run",
            status="completed" if result.get("exit_status") == "Submitted" else "stopped",
            exit_status=result.get("exit_status", ""),
            submission=result.get("submission", ""),
            turn=1,
        )
        logger.emit(
            "run_end",
            exit_status=result.get("exit_status", ""),
            submission=result.get("submission", ""),
            model_calls=getattr(agent, "n_calls", None),
            model_cost=getattr(agent, "cost", None),
            trajectory_path=config["logging"]["trajectory_path"],
        )
        logger.emit("task_end", component="run", status="closed", turn=1)
        return result
    except Exception as exc:
        logger.emit(
            "turn_end",
            component="run",
            status="failed",
            exit_status=type(exc).__name__,
            submission="",
            exception=str(exc),
            turn=1,
        )
        logger.emit("run_end", exit_status="exception", exception_type=type(exc).__name__, exception=str(exc))
        logger.emit("task_end", component="run", status="failed", turn=1)
        raise
