"""Agent construction for the project-owned framework."""

import copy

from game_agent.framework import Agent, Environment, Model
from game_agent.framework.agents.default import DefaultAgent
from game_agent.registry import COMPONENTS


def register_builtin_agents() -> None:
    COMPONENTS.register("agent", "default", DefaultAgent)


def get_agent(model: Model, env: Environment, config: dict, *, default_type: str = "default") -> Agent:
    runtime_keys = {"event_sink", "event_context_sink", "skill_runtime", "context_assembler"}
    runtime_values = {key: value for key, value in config.items() if key in runtime_keys}
    config = copy.deepcopy({key: value for key, value in config.items() if key not in runtime_keys})
    config.update(runtime_values)
    agent_type = config.pop("agent_class", default_type)
    agent_type = {"game_agent.framework.agents.default.DefaultAgent": "default"}.get(agent_type, agent_type)
    register_builtin_agents()
    return COMPONENTS.create("agent", agent_type, model, env, **config)


__all__ = ["DefaultAgent", "get_agent", "register_builtin_agents"]
