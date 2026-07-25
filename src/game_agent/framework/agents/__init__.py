"""Agent construction for the project-owned framework."""

import copy

from game_agent.framework import Agent, Environment, Model
from game_agent.framework.agents.default import DefaultAgent


def get_agent(model: Model, env: Environment, config: dict, *, default_type: str = "default") -> Agent:
    config = copy.deepcopy(config)
    agent_type = config.pop("agent_class", default_type)
    if agent_type not in {"default", "game_agent.framework.agents.default.DefaultAgent"}:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return DefaultAgent(model, env, **config)


__all__ = ["DefaultAgent", "get_agent"]
