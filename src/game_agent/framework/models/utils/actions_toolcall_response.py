"""PowerShell and submit tool protocol for Responses-compatible APIs."""

import json
import time

from jinja2 import StrictUndefined, Template

from game_agent.framework.exceptions import FormatError
from game_agent.aci.schemas import QUERY_TOOL_NAMES
from game_agent.framework.models.utils.actions_toolcall import AGENT_TOOLS, validate_tool_arguments


RESPONSE_TOOLS = [
    {"type": "function", **tool["function"]}
    for tool in AGENT_TOOLS
]


def select_response_tools(structured_queries_enabled: bool = True) -> list[dict]:
    source = AGENT_TOOLS if structured_queries_enabled else [
        tool for tool in AGENT_TOOLS if tool["function"]["name"] in {"powershell", "submit"}
    ]
    return [{"type": "function", **tool["function"]} for tool in source]


def _get(value, key):
    if value is None:
        return None
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)


def finish_reason_from_responses_api(response) -> str | None:
    status = _get(response, "status")
    if status != "incomplete":
        return status
    return "length" if _get(_get(response, "incomplete_details"), "reason") == "max_output_tokens" else status


def _format_error(text: str) -> FormatError:
    return FormatError(
        {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
            "extra": {"interrupt_type": "FormatError"},
        }
    )


def parse_response_actions(
    output: list, *, format_error_template: str, template_kwargs: dict | None = None
) -> list[dict]:
    template_kwargs = template_kwargs or {}
    calls = []
    for item in output or []:
        if _get(item, "type") == "function_call":
            calls.append(item.model_dump() if hasattr(item, "model_dump") else dict(item))
    if not calls:
        text = Template(format_error_template, undefined=StrictUndefined).render(
            error="No tool calls found. Call an available query tool or powershell to continue, or submit to finish.",
            actions=[], has_tool_calls=False, **template_kwargs,
        )
        raise _format_error(text)

    actions = []
    for call in calls:
        name = call.get("name")
        error = ""
        try:
            arguments = json.loads(call.get("arguments", "{}"))
        except Exception as exc:
            arguments = {}
            error = f"Error parsing tool call arguments: {exc}."
        error += validate_tool_arguments(str(name), arguments)
        if error:
            text = Template(format_error_template, undefined=StrictUndefined).render(
                error=error.strip(), actions=[], has_tool_calls=True, **template_kwargs,
            )
            raise _format_error(text)
        call_id = call.get("call_id") or call.get("id")
        if name == "powershell":
            actions.append({"tool": "powershell", "command": arguments["command"], "tool_call_id": call_id})
        elif name == "submit":
            actions.append({"tool": "submit", "answer": arguments["answer"], "tool_call_id": call_id})
        elif name in QUERY_TOOL_NAMES:
            actions.append({"tool": name, "arguments": arguments, "tool_call_id": call_id})
    if any(action["tool"] == "submit" for action in actions) and len(actions) != 1:
        text = Template(format_error_template, undefined=StrictUndefined).render(
            error="submit must be the only tool call in a response.",
            actions=[], has_tool_calls=True, **template_kwargs,
        )
        raise _format_error(text)
    return actions


def format_response_observations(
    *, actions: list[dict], outputs: list[dict], observation_template: str,
    template_vars: dict | None = None, multimodal_regex: str = "",
) -> list[dict]:
    not_executed = {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    padded = outputs + [not_executed] * (len(actions) - len(outputs))
    messages = []
    for action, output in zip(actions, padded):
        content = Template(observation_template, undefined=StrictUndefined).render(
            output=output, **(template_vars or {})
        )
        messages.append(
            {
                "type": "function_call_output",
                "call_id": action.get("tool_call_id"),
                "output": content,
                "extra": {
                    "returncode": output.get("returncode"),
                    "timestamp": time.time(),
                    "exception_info": output.get("exception_info"),
                    **output.get("extra", {}),
                },
            }
        )
    return messages
