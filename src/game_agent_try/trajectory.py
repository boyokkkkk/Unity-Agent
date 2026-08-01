from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TRAJECTORY_SCHEMA_VERSION = "game-agent-trajectory-v1"
UPSTREAM_TRAJECTORY_FORMAT = "mini-swe-agent-1.1"


class TrajectorySchemaError(ValueError):
    pass


def validate_trajectory(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the stable public envelope while allowing component-specific extensions."""
    if data.get("schema_version") != TRAJECTORY_SCHEMA_VERSION:
        raise TrajectorySchemaError("Unsupported or missing trajectory schema_version")
    if data.get("trajectory_format") != UPSTREAM_TRAJECTORY_FORMAT:
        raise TrajectorySchemaError("Unsupported or missing upstream trajectory_format")
    if not isinstance(data.get("messages"), list):
        raise TrajectorySchemaError("messages must be a list")
    if not isinstance(data.get("turn_results"), list):
        raise TrajectorySchemaError("turn_results must be a list")
    if not isinstance(data.get("applied_skills"), list):
        raise TrajectorySchemaError("applied_skills must be a list")
    info = data.get("info")
    if not isinstance(info, dict):
        raise TrajectorySchemaError("info must be an object")
    required_info = {"framework_version", "exit_status", "submission", "model_stats", "config"}
    missing = required_info - set(info)
    if missing:
        raise TrajectorySchemaError(f"Missing trajectory info fields: {sorted(missing)}")
    if not isinstance(info["model_stats"], dict) or not isinstance(info["config"], dict):
        raise TrajectorySchemaError("info.model_stats and info.config must be objects")
    for index, message in enumerate(data["messages"]):
        if not isinstance(message, dict):
            raise TrajectorySchemaError(f"messages[{index}] must be an object")
        if (
            not isinstance(message.get("role"), str)
            and message.get("type") != "function_call_output"
            and message.get("object") != "response"
        ):
            raise TrajectorySchemaError(f"messages[{index}] must have a role or supported response type")
    return data


def write_trajectory(path: Path, data: dict[str, Any]) -> None:
    """Validate and atomically write a UTF-8 trajectory."""
    validate_trajectory(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
