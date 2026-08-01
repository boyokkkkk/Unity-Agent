from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field

from game_agent_try.framework.exceptions import FormatError
from game_agent_try.framework.models import GLOBAL_MODEL_STATS
from game_agent_try.framework.models.utils.actions_toolcall import (
    AGENT_TOOLS,
    format_toolcall_observation_messages,
    parse_toolcall_actions,
    select_agent_tools,
)
from game_agent_try.framework.models.utils.openai_multimodal import expand_multimodal_content
from game_agent_try.framework.models.utils.retry import retry


logger = logging.getLogger("openrouter_model")


class OpenRouterModelConfig(BaseModel):
    model_name: str
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    cost_tracking: Literal["default", "ignore_errors"] = os.getenv("MSWEA_COST_TRACKING", "default")
    format_error_template: str = "{{ error }}"
    observation_template: str = (
        "{% if output.exception_info %}<exception>{{output.exception_info}}</exception>\n{% endif %}"
        "<returncode>{{output.returncode}}</returncode>\n<output>\n{{output.output}}</output>"
    )
    multimodal_regex: str = ""
    request_timeout_seconds: int = 60
    structured_query_tools_enabled: bool = True


class OpenRouterAPIError(Exception):
    pass


class OpenRouterAuthenticationError(OpenRouterAPIError):
    pass


class OpenRouterRateLimitError(OpenRouterAPIError):
    pass


class _DictObject:
    def __init__(self, data: dict):
        self.id = data.get("id")
        self.function = _DictObject(data.get("function", {})) if "function" in data else None
        self.name = data.get("name")
        self.arguments = data.get("arguments")


class OpenRouterModel:
    abort_exceptions = [OpenRouterAuthenticationError, KeyboardInterrupt]

    def __init__(self, **kwargs):
        self.config = OpenRouterModelConfig(**kwargs)
        self.agent_tools = select_agent_tools(self.config.structured_query_tools_enabled)
        self._api_url = "https://openrouter.ai/api/v1/chat/completions"
        self._api_key = os.getenv("OPENROUTER_API_KEY", "")

    def set_available_tool_names(self, tool_names: tuple[str, ...]) -> None:
        self.agent_tools = select_agent_tools(
            self.config.structured_query_tools_enabled,
            tool_names,
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}

    def _post(self, payload: dict) -> dict:
        try:
            response = requests.post(
                self._api_url,
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=self.config.request_timeout_seconds,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as exc:
            if response.status_code == 401:
                raise OpenRouterAuthenticationError("OpenRouter authentication failed; set OPENROUTER_API_KEY") from exc
            if response.status_code == 429:
                raise OpenRouterRateLimitError("OpenRouter rate limit exceeded") from exc
            raise OpenRouterAPIError(f"OpenRouter HTTP {response.status_code}: {response.text}") from exc
        except requests.exceptions.RequestException as exc:
            raise OpenRouterAPIError(f"OpenRouter request failed: {exc}") from exc

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        return [{key: value for key, value in message.items() if key != "extra"} for message in messages]

    def _query(self, messages: list[dict], **kwargs) -> dict:
        return self._post(
            {
                "model": self.config.model_name,
                "messages": messages,
                "tools": self.agent_tools,
                "usage": {"include": True},
                **(self.config.model_kwargs | kwargs),
            }
        )

    @staticmethod
    def _estimate(value: Any) -> int:
        return max(1, len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")))

    def estimate_input_tokens(self, messages: list[dict]) -> int:
        return self._estimate(self._prepare_messages_for_api(messages)) + self._estimate(self.agent_tools)

    def estimate_tool_schema_tokens(self) -> int:
        return self._estimate(self.agent_tools)

    def _calculate_cost(self, response: dict) -> dict[str, float]:
        cost = float(response.get("usage", {}).get("cost") or 0.0)
        if cost <= 0 and self.config.cost_tracking != "ignore_errors":
            raise RuntimeError("OpenRouter response did not include a positive usage.cost")
        return {"cost": cost}

    def _calculate_usage(self, response: dict, messages: list[dict]) -> dict[str, int]:
        usage = response.get("usage", {})
        prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or self.estimate_input_tokens(messages))
        completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or self._estimate(response))
        return {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": int(usage.get("total_tokens") or prompt + completion),
        }

    def query(self, messages: list[dict], **kwargs) -> dict:
        prepared = self._prepare_messages_for_api(messages)
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = self._query(prepared, **kwargs)
        cost = self._calculate_cost(response)
        usage = self._calculate_usage(response, messages)
        GLOBAL_MODEL_STATS.add(cost["cost"])
        try:
            calls = [_DictObject(call) for call in response["choices"][0]["message"].get("tool_calls", [])]
            actions = parse_toolcall_actions(
                calls,
                format_error_template=self.config.format_error_template,
                template_kwargs={"finish_reason": response["choices"][0].get("finish_reason")},
            )
        except FormatError as exc:
            exc.messages[0].setdefault("extra", {}).update(cost | usage | {"response": response})
            raise
        message = dict(response["choices"][0]["message"])
        message["extra"] = {"actions": actions, "response": response, **cost, **usage, "timestamp": time.time()}
        return message

    def format_message(self, **kwargs) -> dict:
        return expand_multimodal_content(kwargs, pattern=self.config.multimodal_regex)

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return format_toolcall_observation_messages(
            actions=message.get("extra", {}).get("actions", []), outputs=outputs,
            observation_template=self.config.observation_template, template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return self.config.model_dump()

    def serialize(self) -> dict:
        return {"info": {"config": {
            "model": self.config.model_dump(mode="json"),
            "model_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
        }}}
