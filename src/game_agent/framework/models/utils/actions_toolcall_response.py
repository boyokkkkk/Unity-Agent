"""PowerShell and submit tool protocol for Responses-compatible APIs."""

import json
import time

from jinja2 import StrictUndefined, Template

from game_agent.framework.exceptions import FormatError
from game_agent.framework.models.utils.actions_toolcall import AGENT_TOOLS


RESPONSE_TOOLS = [
    {"type": "function", **tool["function"]}
    for tool in AGENT_TOOLS
]


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
            error="No tool calls found. Call powershell to continue or submit to finish the task.",
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
        if name == "powershell":
            if not isinstance(arguments.get("command"), str) or not arguments["command"].strip():
                error += " Missing non-empty 'command' argument in powershell tool call."
        elif name == "submit":
            if not isinstance(arguments.get("answer"), str) or not arguments["answer"].strip():
                error += " Missing non-empty 'answer' argument in submit tool call."
        else:
            error += f" Unknown tool '{name}'. Expected powershell or submit."
        if error:
            text = Template(format_error_template, undefined=StrictUndefined).render(
                error=error.strip(), actions=[], has_tool_calls=True, **template_kwargs,
            )
            raise _format_error(text)
        call_id = call.get("call_id") or call.get("id")
        if name == "powershell":
            actions.append({"tool": "powershell", "command": arguments["command"], "tool_call_id": call_id})
        else:
            actions.append({"tool": "submit", "answer": arguments["answer"], "tool_call_id": call_id})
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

