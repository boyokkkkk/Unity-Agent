"""Execution environments provided by the project-owned framework."""

from game_agent_try.framework.environments.local import LocalEnvironment
from game_agent_try.registry import COMPONENTS


def register_builtin_environments() -> None:
    COMPONENTS.register("environment", "local", LocalEnvironment)


def get_environment(config: dict, *, default_type: str = "local"):
    values = dict(config)
    environment_type = values.pop("environment_class", default_type)
    environment_type = {
        "game_agent.framework.environments.local.LocalEnvironment": "local"
    }.get(environment_type, environment_type)
    register_builtin_environments()
    return COMPONENTS.create("environment", environment_type, **values)

__all__ = ["LocalEnvironment", "get_environment", "register_builtin_environments"]
