"""Model construction and process-wide usage accounting."""

import copy
import os
import threading

from game_agent_try.registry import COMPONENTS


class GlobalModelStats:
    def __init__(self) -> None:
        self._cost = 0.0
        self._n_calls = 0
        self._lock = threading.Lock()
        self.cost_limit = float(os.getenv("MSWEA_GLOBAL_COST_LIMIT", "0"))
        self.call_limit = int(os.getenv("MSWEA_GLOBAL_CALL_LIMIT", "0"))

    def add(self, cost: float) -> None:
        with self._lock:
            self._cost += cost
            self._n_calls += 1
        if 0 < self.cost_limit < self._cost or 0 < self.call_limit < self._n_calls:
            raise RuntimeError(f"Global cost/call limit exceeded: ${self._cost:.4f} / {self._n_calls}")

    @property
    def cost(self) -> float:
        return self._cost

    @property
    def n_calls(self) -> int:
        return self._n_calls


GLOBAL_MODEL_STATS = GlobalModelStats()


def register_builtin_models() -> None:
    from game_agent_try.framework.models.litellm_model import LitellmModel
    from game_agent_try.framework.models.litellm_response_model import LitellmResponseModel
    from game_agent_try.framework.models.openrouter_model import OpenRouterModel
    from game_agent_try.framework.models.openrouter_response_model import OpenRouterResponseModel

    for name, factory in {
        "litellm": LitellmModel,
        "litellm_response": LitellmResponseModel,
        "responses": LitellmResponseModel,
        "openrouter": OpenRouterModel,
        "openrouter_response": OpenRouterResponseModel,
    }.items():
        COMPONENTS.register("model", name, factory)


def get_model(input_model_name: str, config: dict | None = None):
    model_config = copy.deepcopy(config or {})
    model_class = model_config.pop("model_class", "litellm")
    model_class = {
        "": "litellm",
        "game_agent.framework.models.litellm_model.LitellmModel": "litellm",
    }.get(model_class, model_class)
    register_builtin_models()
    model_config["model_name"] = input_model_name
    return COMPONENTS.create("model", model_class, **model_config)


__all__ = ["GLOBAL_MODEL_STATS", "GlobalModelStats", "get_model", "register_builtin_models"]
