from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import litellm

from game_agent.framework.exceptions import FormatError
from game_agent.framework.models import GLOBAL_MODEL_STATS
from game_agent.framework.models.litellm_model import LitellmModel, LitellmModelConfig
from game_agent.framework.models.utils.actions_toolcall_response import (
    RESPONSE_TOOLS,
    finish_reason_from_responses_api,
    format_response_observations,
    parse_response_actions,
)
from game_agent.framework.models.utils.retry import retry


logger = logging.getLogger("litellm_response_model")


class LitellmResponseModelConfig(LitellmModelConfig):
    pass


def _dump(response: Any) -> dict:
    return response.model_dump(mode="json") if hasattr(response, "model_dump") else dict(response)


class LitellmResponseModel(LitellmModel):
    """Stateless LiteLLM Responses API adapter with native PowerShell/submit tools."""

    def __init__(self, *, config_class: Callable = LitellmResponseModelConfig, **kwargs):
        super().__init__(config_class=config_class, **kwargs)

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        prepared = []
        for message in messages:
            if message.get("object") == "response":
                prepared.extend(
                    {key: value for key, value in item.items() if key != "extra"}
                    for item in message.get("output", [])
                )
            else:
                prepared.append({key: value for key, value in message.items() if key != "extra"})
        return prepared

    def _query(self, messages: list[dict], **kwargs):
        parameters = self.config.model_kwargs | kwargs
        if "max_tokens" in parameters and "max_output_tokens" not in parameters:
            parameters["max_output_tokens"] = parameters.pop("max_tokens")
        return litellm.responses(
            model=self.config.model_name,
            input=messages,
            tools=RESPONSE_TOOLS,
            **parameters,
        )

    def estimate_input_tokens(self, messages: list[dict[str, str]]) -> int:
        prepared = self._prepare_messages_for_api(messages)
        return self._conservative_token_estimate(prepared) + self._conservative_token_estimate(RESPONSE_TOOLS)

    def _calculate_usage(self, response: Any, messages: list[dict]) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if isinstance(response, dict):
            usage = response.get("usage")

        def value(*names: str) -> int:
            for name in names:
                raw = usage.get(name, 0) if isinstance(usage, dict) else getattr(usage, name, 0) if usage else 0
                if raw:
                    return int(raw)
            return 0

        prompt = value("input_tokens", "prompt_tokens") or self.estimate_input_tokens(messages)
        completion = value("output_tokens", "completion_tokens") or self._conservative_token_estimate(_dump(response))
        total = value("total_tokens") or prompt + completion
        return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}

    def query(self, messages: list[dict[str, str]], **kwargs) -> dict:
        prepared = self._prepare_messages_for_api(messages)
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = self._query(prepared, **kwargs)
        cost = self._calculate_cost(response)
        usage = self._calculate_usage(response, messages)
        GLOBAL_MODEL_STATS.add(cost["cost"])
        try:
            actions = parse_response_actions(
                getattr(response, "output", response.get("output", []) if isinstance(response, dict) else []),
                format_error_template=self.config.format_error_template,
                template_kwargs={"finish_reason": finish_reason_from_responses_api(response)},
            )
        except FormatError as exc:
            exc.messages[0].setdefault("extra", {}).update(cost | usage)
            try:
                exc.messages[0]["extra"]["response"] = _dump(response)
            except Exception:
                exc.messages[0]["extra"]["response"] = repr(response)
            raise
        message = _dump(response)
        message["extra"] = {"actions": actions, **cost, **usage, "timestamp": time.time()}
        return message

    def format_message(self, **kwargs) -> dict:
        content = kwargs.get("content", "")
        message = {
            "type": "message",
            "role": kwargs.get("role", "user"),
            "content": [{"type": "input_text", "text": content}] if isinstance(content, str) else content,
        }
        if kwargs.get("extra") is not None:
            message["extra"] = kwargs["extra"]
        return message

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return format_response_observations(
            actions=message.get("extra", {}).get("actions", []),
            outputs=outputs,
            observation_template=self.config.observation_template,
            template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )

