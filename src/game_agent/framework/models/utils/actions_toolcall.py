"""Parse actions & format observations with toolcalls"""

import json
import time

from jinja2 import StrictUndefined, Template

from game_agent.framework.exceptions import FormatError
from game_agent.framework.models.utils.openai_multimodal import expand_multimodal_content
from game_agent.aci.schemas import ACI_TOOL_NAMES, ACI_TOOLS

POWERSHELL_TOOL = {
    "type": "function",
    "function": {
        "name": "powershell",
        "description": "Execute a Windows PowerShell command in the Unity project",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "A Windows PowerShell command; Unix shell commands are not available",
                }
            },
            "required": ["command"],
        },
    },
}

SUBMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "submit",
        "description": "Finish the task and return the final answer to the user",
        "parameters": {
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "description": "The complete final answer, including relevant paths, changes, and verification",
                }
            },
            "required": ["answer"],
        },
    },
}

CORE_AGENT_TOOLS = [POWERSHELL_TOOL, SUBMIT_TOOL]
AGENT_TOOLS = [POWERSHELL_TOOL, *ACI_TOOLS, SUBMIT_TOOL]
TOOL_SCHEMAS = {tool["function"]["name"]: tool["function"]["parameters"] for tool in AGENT_TOOLS}


def select_agent_tools(structured_queries_enabled: bool = True) -> list[dict]:
    return AGENT_TOOLS if structured_queries_enabled else CORE_AGENT_TOOLS


def validate_tool_arguments(tool_name: str, args: object) -> str:
    """Return a compact validation error for a locally executed function call."""
    schema = TOOL_SCHEMAS.get(tool_name)
    if schema is None:
        return f"Unknown tool '{tool_name}'."
    if not isinstance(args, dict):
        return f"Arguments for '{tool_name}' must be an object."
    errors: list[str] = []
    for key in schema.get("required", []):
        if key not in args or (isinstance(args.get(key), str) and not args[key].strip()):
            errors.append(f"Missing non-empty '{key}' argument.")
    expected_types = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    properties = schema.get("properties", {})
    for key, value in args.items():
        if key not in properties and schema.get("additionalProperties") is False:
            errors.append(f"Unknown argument '{key}'.")
            continue
        expected = expected_types.get(properties.get(key, {}).get("type"))
        if expected is not None and not isinstance(value, expected):
            errors.append(f"Argument '{key}' must be {properties[key]['type']}.")
    return " ".join(errors)


def parse_toolcall_actions(
    tool_calls: list, *, format_error_template: str, template_kwargs: dict | None = None
) -> list[dict]:
    """Parse tool calls from the response. Raises FormatError if unknown tool or invalid args.

    ``template_kwargs`` are extra variables exposed to ``format_error_template`` (e.g.
    ``{"finish_reason": ...}`` so a template can distinguish a real format mistake from a
    ``max_tokens`` truncation).
    """
    template_kwargs = template_kwargs or {}
    if not tool_calls:
        raise FormatError(
            {
                "role": "user",
                "content": Template(format_error_template, undefined=StrictUndefined).render(
                    error="No tool calls found. Call an available query tool or powershell to continue, or submit to finish.",
                    actions=[],
                    has_tool_calls=False,
                    **template_kwargs,
                ),
                "extra": {"interrupt_type": "FormatError"},
            }
        )
    actions = []
    for tool_call in tool_calls:
        error_msg = ""
        args = {}
        try:
            args = json.loads(tool_call.function.arguments)
        except Exception as e:
            error_msg = f"Error parsing tool call arguments: {e}."
        tool_name = tool_call.function.name
        error_msg += validate_tool_arguments(tool_name, args)
        if error_msg:
            raise FormatError(
                {
                    "role": "user",
                    "content": Template(format_error_template, undefined=StrictUndefined).render(
                        actions=[], error=error_msg.strip(), has_tool_calls=True, **template_kwargs
                    ),
                    "extra": {"interrupt_type": "FormatError"},
                }
            )
        if tool_name == "powershell":
            actions.append(
                {"tool": "powershell", "command": args["command"], "tool_call_id": tool_call.id}
            )
        elif tool_name == "submit":
            actions.append({"tool": "submit", "answer": args["answer"], "tool_call_id": tool_call.id})
        elif tool_name in ACI_TOOL_NAMES:
            actions.append({"tool": tool_name, "arguments": args, "tool_call_id": tool_call.id})
    if any(action["tool"] == "submit" for action in actions) and len(actions) != 1:
        raise FormatError(
            {
                "role": "user",
                "content": Template(format_error_template, undefined=StrictUndefined).render(
                    actions=[],
                    error="submit must be the only tool call in a response.",
                    has_tool_calls=True,
                    **template_kwargs,
                ),
                "extra": {"interrupt_type": "FormatError"},
            }
        )
    return actions


def format_toolcall_observation_messages(
    *,
    actions: list[dict],
    outputs: list[dict],
    observation_template: str,
    template_vars: dict | None = None,
    multimodal_regex: str = "",
) -> list[dict]:
    """Format execution outputs into tool result messages."""
    not_executed = {"output": "", "returncode": -1, "exception_info": "action was not executed"}
    padded_outputs = outputs + [not_executed] * (len(actions) - len(outputs))
    results = []
    for action, output in zip(actions, padded_outputs):
        content = Template(observation_template, undefined=StrictUndefined).render(
            output=output, **(template_vars or {})
        )
        msg = {
            "content": content,
            "extra": {
                "returncode": output.get("returncode"),
                "timestamp": time.time(),
                "exception_info": output.get("exception_info"),
                **output.get("extra", {}),
            },
        }
        if "tool_call_id" in action:
            msg["tool_call_id"] = action["tool_call_id"]
            msg["role"] = "tool"
        else:
            msg["role"] = "user"  # human issued commands
        if multimodal_regex:
            msg = expand_multimodal_content(msg, pattern=multimodal_regex)
        results.append(msg)
    return results
