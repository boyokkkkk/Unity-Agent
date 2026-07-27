"""Minimal linear-history Agent derived from mini-SWE-agent."""

import json
import logging
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from game_agent.framework import Environment, Model, __version__
from game_agent.framework.exceptions import FormatError, InterruptAgentFlow, LimitsExceeded, TimeExceeded
from game_agent.framework.utils.serialize import recursive_merge


class AgentConfig(BaseModel):
    """Runtime limits and prompt templates for the default Agent."""

    system_template: str
    instance_template: str
    step_limit: int = 0
    cost_limit: float = 3.0
    wall_time_limit_seconds: int = 0
    max_consecutive_format_errors: int = 3
    output_path: Path | None = None


class DefaultAgent:
    def __init__(
        self,
        model: Model,
        env: Environment,
        *,
        config_class: type = AgentConfig,
        event_sink: Callable[..., object] | None = None,
        event_context_sink: Callable[..., object] | None = None,
        **kwargs,
    ):
        """Create an Agent; event hooks are optional and preserve upstream behavior."""
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.event_sink = event_sink
        self.event_context_sink = event_context_sink
        self.extra_template_vars = {}
        self.logger = logging.getLogger("agent")
        self.cost = 0.0
        self.n_calls = 0
        self.n_tool_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()
        self._turn_start_time = self._start_time
        self._turn_call_base = 0
        self._turn_cost_base = 0.0
        self.turn = 0
        self.round = 0
        self.turn_results: list[dict] = []
        self.last_result: dict = {}
        self._last_interrupt: InterruptAgentFlow | None = None

    def _emit(self, event: str, *, component: str, **data) -> None:
        if self.event_sink:
            self.event_sink(event, component=component, turn=self.turn, round=self.round, **data)

    def _set_event_context(self) -> None:
        if self.event_context_sink:
            self.event_context_sink(turn=self.turn, round=self.round)

    def get_template_vars(self, **kwargs) -> dict:
        return recursive_merge(
            self.config.model_dump(),
            self.env.get_template_vars(),
            self.model.get_template_vars(),
            {
                "n_model_calls": self.n_calls,
                "model_cost": self.cost,
                "elapsed_seconds": int(time.time() - self._start_time),
            },
            self.extra_template_vars,
            kwargs,
        )

    def _render_template(self, template: str) -> str:
        return Template(template, undefined=StrictUndefined).render(**self.get_template_vars())

    def add_messages(self, *messages: dict) -> list[dict]:
        self.logger.debug(messages)
        self.messages.extend(messages)
        return list(messages)

    def handle_uncaught_exception(self, error: Exception) -> list[dict]:
        return self.add_messages(
            self.model.format_message(
                role="exit",
                content=str(error),
                extra={
                    "exit_status": type(error).__name__,
                    "submission": "",
                    "exception_str": str(error),
                    "traceback": traceback.format_exc(),
                },
            )
        )

    def _reset_task(self) -> None:
        self.messages = []
        self.extra_template_vars = {}
        self.cost = 0.0
        self.n_calls = 0
        self.n_tool_calls = 0
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()
        self.turn = 0
        self.round = 0
        self.turn_results = []
        self.last_result = {}
        self._last_interrupt = None

    def _begin_turn(self) -> None:
        self._turn_start_time = time.time()
        self._turn_call_base = self.n_calls
        self._turn_cost_base = self.cost
        self.n_consecutive_format_errors = 0
        self._last_interrupt = None
        self._set_event_context()

    def run(self, task: str = "", **kwargs) -> dict:
        """Run one legacy task and retain its terminal exit message."""
        self._reset_task()
        self.turn = 1
        self._begin_turn()
        self.extra_template_vars |= {"task": task, **kwargs}
        self.add_messages(
            self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
            self.model.format_message(role="user", content=self._render_template(self.config.instance_template)),
        )
        self.last_result = self._run_loop()
        return self.last_result

    def run_turn(self, task: str, **kwargs) -> dict:
        """Run one interactive turn while retaining continuation-safe context."""
        self.turn += 1
        self.round = 0
        self._begin_turn()
        self.extra_template_vars |= {"task": task, **kwargs}
        if not self.messages:
            self.add_messages(
                self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
                self.model.format_message(role="user", content=self._render_template(self.config.instance_template)),
            )
        else:
            self.add_messages(self.model.format_message(role="user", content=task))

        try:
            result = self._run_loop()
        except BaseException as error:
            if self.messages and self.messages[-1].get("role") == "exit":
                self.messages.pop()
            self.last_result = {
                "exit_status": type(error).__name__,
                "submission": "",
                "error": str(error),
            }
            self.save(self.config.output_path)
            raise
        if self.messages and self.messages[-1].get("role") == "exit":
            self.messages.pop()
        submission = result.get("submission", "")
        self.last_result = dict(result)
        if (
            result.get("exit_status") == "Submitted"
            and self.messages
            and self.messages[-1].get("extra", {}).get("actions")
        ):
            action_message = self.messages[-1]
            actions = action_message.get("extra", {}).get("actions", [])
            tool_output = getattr(self._last_interrupt, "tool_output", None)
            outputs = [
                tool_output or {"output": "Task submitted.", "returncode": 0, "exception_info": ""}
                for _ in actions
            ]
            self.add_messages(
                *self.model.format_observation_messages(
                    action_message,
                    outputs,
                    self.get_template_vars(),
                )
            )
        if submission:
            self.add_messages(
                self.model.format_message(
                    role="assistant",
                    content=submission,
                    extra={**dict(result), "turn_result": dict(result), "turn": self.turn},
                )
            )
        self.turn_results.append({"turn": self.turn, **result})
        self.save(self.config.output_path)
        return result

    def _run_loop(self) -> dict:
        while True:
            try:
                self.step()
                self.n_consecutive_format_errors = 0
            except FormatError as error:
                self.cost += error.messages[0].get("extra", {}).get("cost", 0.0)
                self.n_consecutive_format_errors += 1
                if 0 < self.config.max_consecutive_format_errors <= self.n_consecutive_format_errors:
                    self.add_messages(
                        *error.messages,
                        {
                            "role": "exit",
                            "content": "RepeatedFormatError",
                            "extra": {"exit_status": "RepeatedFormatError", "submission": ""},
                        },
                    )
                else:
                    self.add_messages(*error.messages)
            except InterruptAgentFlow as interrupt:
                self._last_interrupt = interrupt
                self.add_messages(*interrupt.messages)
            except Exception as error:
                self.handle_uncaught_exception(error)
                raise
            finally:
                self.save(self.config.output_path)
            if self.messages[-1].get("role") == "exit":
                break
        return self.messages[-1].get("extra", {})

    def step(self) -> list[dict]:
        """Query the Model, execute actions, and append observations."""
        self.round += 1
        self._set_event_context()
        self._emit(
            "agent_round_start",
            component="agent",
            message_count=len(self.messages),
            model_calls=self.n_calls,
        )
        return self.execute_actions(self.query())

    def query(self) -> dict:
        """Query the Model with per-turn limits and component telemetry."""
        turn_calls = self.n_calls - self._turn_call_base
        turn_cost = self.cost - self._turn_cost_base
        if 0 < self.config.step_limit <= turn_calls or 0 < self.config.cost_limit <= turn_cost:
            self._emit(
                "agent_limit_reached",
                component="agent",
                limit="step_or_cost",
                turn_model_calls=turn_calls,
                turn_cost=turn_cost,
            )
            raise LimitsExceeded(
                {
                    "role": "exit",
                    "content": "LimitsExceeded",
                    "extra": {"exit_status": "LimitsExceeded", "submission": ""},
                }
            )
        elapsed = int(time.time() - self._turn_start_time)
        if 0 < self.config.wall_time_limit_seconds <= elapsed:
            self._emit(
                "agent_limit_reached",
                component="agent",
                limit="wall_time",
                elapsed_seconds=elapsed,
            )
            raise TimeExceeded(
                {
                    "role": "exit",
                    "content": "TimeExceeded",
                    "extra": {"exit_status": "TimeExceeded", "submission": ""},
                }
            )

        self.n_calls += 1
        started = time.perf_counter()
        model_name = getattr(getattr(self.model, "config", None), "model_name", type(self.model).__name__)
        self._emit("model_start", component="model", model=model_name, message_count=len(self.messages))
        try:
            message = self.model.query(self.messages)
        except BaseException as error:
            self._emit(
                "model_error",
                component="model",
                model=model_name,
                duration_ms=int((time.perf_counter() - started) * 1000),
                error_type=type(error).__name__,
                error=str(error),
            )
            raise

        self.cost += message.get("extra", {}).get("cost", 0.0)
        self.add_messages(message)
        actions = message.get("extra", {}).get("actions", [])
        self._emit(
            "model_end",
            component="model",
            model=model_name,
            duration_ms=int((time.perf_counter() - started) * 1000),
            outcome="tool_call" if actions else "message",
            action_count=len(actions),
            content=message.get("content", ""),
        )
        return message

    def execute_actions(self, message: dict) -> list[dict]:
        """Execute actions and report the observation transition."""
        actions = message.get("extra", {}).get("actions", [])
        self.n_tool_calls += len(actions)
        outputs = [self.env.execute(action) for action in actions]
        observations = self.model.format_observation_messages(message, outputs, self.get_template_vars())
        added = self.add_messages(*observations)
        if actions:
            self._emit(
                "agent_observation_added",
                component="agent",
                action_count=len(actions),
                observation_count=len(observations),
                message_count=len(self.messages),
            )
        return added

    def serialize(self, *extra_dicts) -> dict:
        """Serialize the current linear history and task totals."""
        last_message = self.messages[-1] if self.messages else {}
        last_extra = self.last_result or last_message.get("extra", {})
        agent_data = {
            "info": {
                "model_stats": {
                    "instance_cost": self.cost,
                    "api_calls": self.n_calls,
                    "tool_calls": self.n_tool_calls,
                },
                "config": {
                    "agent": self.config.model_dump(mode="json"),
                    "agent_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                },
                "framework_version": __version__,
                "exit_status": last_extra.get("exit_status", ""),
                "submission": last_extra.get("submission", ""),
            },
            "messages": self.messages,
            "turn_results": self.turn_results,
            "trajectory_format": "mini-swe-agent-1.1",
        }
        return recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)

    def save(self, path: Path | None, *extra_dicts) -> dict:
        """Save the serialized trajectory when a path is configured."""
        data = self.serialize(*extra_dicts)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
