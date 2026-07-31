from __future__ import annotations

import logging
import time

from game_agent.framework.exceptions import FormatError
from game_agent.framework.models import GLOBAL_MODEL_STATS
from game_agent.framework.models.openrouter_model import OpenRouterModel, OpenRouterModelConfig
from game_agent.framework.models.utils.actions_toolcall_response import (
    RESPONSE_TOOLS,
    finish_reason_from_responses_api,
    format_response_observations,
    parse_response_actions,
    select_response_tools,
)
from game_agent.framework.models.utils.retry import retry


logger = logging.getLogger("openrouter_response_model")


class OpenRouterResponseModelConfig(OpenRouterModelConfig):
    pass


class OpenRouterResponseModel(OpenRouterModel):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.config = OpenRouterResponseModelConfig(**kwargs)
        self.response_tools = select_response_tools(self.config.structured_query_tools_enabled)
        self._api_url = "https://openrouter.ai/api/v1/responses"

    def set_available_tool_names(self, tool_names: tuple[str, ...]) -> None:
        super().set_available_tool_names(tool_names)
        self.response_tools = select_response_tools(
            self.config.structured_query_tools_enabled,
            tool_names,
        )

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

    def _query(self, messages: list[dict], **kwargs) -> dict:
        parameters = self.config.model_kwargs | kwargs
        if "max_tokens" in parameters and "max_output_tokens" not in parameters:
            parameters["max_output_tokens"] = parameters.pop("max_tokens")
        return self._post({"model": self.config.model_name, "input": messages, "tools": self.response_tools, **parameters})

    def estimate_input_tokens(self, messages: list[dict]) -> int:
        prepared = self._prepare_messages_for_api(messages)
        return self._estimate(prepared) + self._estimate(self.response_tools)

    def estimate_tool_schema_tokens(self) -> int:
        return self._estimate(self.response_tools)

    def query(self, messages: list[dict], **kwargs) -> dict:
        prepared = self._prepare_messages_for_api(messages)
        for attempt in retry(logger=logger, abort_exceptions=self.abort_exceptions):
            with attempt:
                response = self._query(prepared, **kwargs)
        cost = self._calculate_cost(response)
        usage = self._calculate_usage(response, messages)
        GLOBAL_MODEL_STATS.add(cost["cost"])
        try:
            actions = parse_response_actions(
                response.get("output", []),
                format_error_template=self.config.format_error_template,
                template_kwargs={"finish_reason": finish_reason_from_responses_api(response)},
            )
        except FormatError as exc:
            exc.messages[0].setdefault("extra", {}).update(cost | usage | {"response": response})
            raise
        message = dict(response)
        message["extra"] = {"actions": actions, **cost, **usage, "timestamp": time.time()}
        return message

    def format_message(self, **kwargs) -> dict:
        content = kwargs.get("content", "")
        message = {
            "type": "message", "role": kwargs.get("role", "user"),
            "content": [{"type": "input_text", "text": content}] if isinstance(content, str) else content,
        }
        if kwargs.get("extra") is not None:
            message["extra"] = kwargs["extra"]
        return message

    def format_observation_messages(self, message: dict, outputs: list[dict], template_vars=None) -> list[dict]:
        return format_response_observations(
            actions=message.get("extra", {}).get("actions", []), outputs=outputs,
            observation_template=self.config.observation_template, template_vars=template_vars,
            multimodal_regex=self.config.multimodal_regex,
        )
