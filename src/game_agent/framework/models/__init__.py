"""Model construction and process-wide usage accounting."""

import copy
import os
import threading


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


def get_model(input_model_name: str, config: dict | None = None):
    from game_agent.framework.models.litellm_model import LitellmModel

    model_config = copy.deepcopy(config or {})
    model_class = model_config.pop("model_class", "litellm")
    if model_class not in {"", "litellm", "game_agent.framework.models.litellm_model.LitellmModel"}:
        raise ValueError(f"Unknown model class: {model_class}")
    model_config["model_name"] = input_model_name
    return LitellmModel(**model_config)


__all__ = ["GLOBAL_MODEL_STATS", "GlobalModelStats", "get_model"]
