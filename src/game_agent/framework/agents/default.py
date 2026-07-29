"""Minimal linear-history Agent derived from mini-SWE-agent."""

import hashlib
import json
import logging
import time
import traceback
from collections.abc import Callable
from pathlib import Path

from jinja2 import StrictUndefined, Template
from pydantic import BaseModel

from game_agent.framework import Environment, Model, __version__
from game_agent.framework.exceptions import (
    ConsecutiveToolFailuresExceeded,
    FormatError,
    InputTokenLimitExceeded,
    InterruptAgentFlow,
    LimitsExceeded,
    NoProgressExceeded,
    RepeatedActionExceeded,
    Submitted,
    TimeExceeded,
    TotalTokenLimitExceeded,
)
from game_agent.framework.utils.serialize import recursive_merge
from game_agent.trajectory import (
    TRAJECTORY_SCHEMA_VERSION,
    UPSTREAM_TRAJECTORY_FORMAT,
    validate_trajectory,
    write_trajectory,
)


class AgentConfig(BaseModel):
    """Runtime limits and prompt templates for the default Agent."""

    system_template: str
    instance_template: str
    step_limit: int = 0
    cost_limit: float = 3.0
    wall_time_limit_seconds: int = 0
    max_consecutive_format_errors: int = 3
    max_input_tokens: int = 0
    max_output_tokens: int = 0
    max_total_tokens: int = 0
    max_repeated_actions: int = 2
    max_no_progress_rounds: int = 2
    max_consecutive_tool_failures: int = 3
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
        skill_runtime: object | None = None,
        **kwargs,
    ):
        """Create an Agent; event hooks are optional and preserve upstream behavior."""
        self.config = config_class(**kwargs)
        self.messages: list[dict] = []
        self.model = model
        self.env = env
        self.event_sink = event_sink
        self.event_context_sink = event_context_sink
        self.skill_runtime = skill_runtime
        self.applied_skills: list[dict[str, str | int]] = []
        self.extra_template_vars = {}
        self.logger = logging.getLogger("agent")
        self.cost = 0.0
        self.n_calls = 0
        self.n_tool_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.last_input_tokens = 0
        self.consecutive_repeated_actions = 0
        self.no_progress_rounds = 0
        self.consecutive_tool_failures = 0
        self._last_action_hash = ""
        self._last_result_hash = ""
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
            {
                'prompt_tokens': self.prompt_tokens,
                'completion_tokens': self.completion_tokens,
                'total_tokens': self.total_tokens,
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
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.last_input_tokens = 0
        self.consecutive_repeated_actions = 0
        self.no_progress_rounds = 0
        self.consecutive_tool_failures = 0
        self._last_action_hash = ""
        self._last_result_hash = ""
        self.n_consecutive_format_errors = 0
        self._start_time = time.time()
        self.turn = 0
        self.round = 0
        self.turn_results = []
        self.last_result = {}
        self._last_interrupt = None
        self.applied_skills = []

    def _begin_turn(self) -> None:
        self._turn_start_time = time.time()
        self._turn_call_base = self.n_calls
        self._turn_cost_base = self.cost
        self.n_consecutive_format_errors = 0
        self._last_interrupt = None
        self._set_event_context()

    def _with_skill_context(self, task: str, content: str) -> str:
        if self.skill_runtime is None:
            return content
        resolved = self.skill_runtime.resolve(task)
        if not resolved:
            return content
        skill = {
            "name": str(resolved["name"]),
            "instructions": str(resolved["instructions"]),
        }
        self.applied_skills.append({"turn": self.turn, **skill})
        return (
            f"{content}\n\n"
            f"<verified-skill name=\"{skill['name']}\">\n"
            f"{skill['instructions']}\n"
            "</verified-skill>"
        )

    def run(self, task: str = "", **kwargs) -> dict:
        """Run one legacy task and retain its terminal exit message."""
        self._reset_task()
        self.turn = 1
        self._begin_turn()
        self.extra_template_vars |= {"task": task, **kwargs}
        instance_content = self._with_skill_context(
            task,
            self._render_template(self.config.instance_template),
        )
        self.add_messages(
            self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
            self.model.format_message(role="user", content=instance_content),
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
            instance_content = self._with_skill_context(
                task,
                self._render_template(self.config.instance_template),
            )
            self.add_messages(
                self.model.format_message(role="system", content=self._render_template(self.config.system_template)),
                self.model.format_message(role="user", content=instance_content),
            )
        else:
            self.add_messages(
                self.model.format_message(role="user", content=self._with_skill_context(task, task))
            )

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
                self._record_usage(error.messages[0], fallback_prompt_tokens=self.last_input_tokens)
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

        output_token_budget = self._preflight_token_budget()
        self.n_calls += 1
        started = time.perf_counter()
        model_name = getattr(getattr(self.model, "config", None), "model_name", type(self.model).__name__)
        self._emit("model_start", component="model", model=model_name, message_count=len(self.messages))
        try:
            query_kwargs = {'max_tokens': output_token_budget} if output_token_budget > 0 else {}
            message = self.model.query(self.messages, **query_kwargs)
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
        self._record_usage(message, fallback_prompt_tokens=self.last_input_tokens)
        self._emit(
            'model_usage',
            component='model',
            prompt_tokens=message.get('extra', {}).get('prompt_tokens', 0),
            completion_tokens=message.get('extra', {}).get('completion_tokens', 0),
            request_total_tokens=message.get('extra', {}).get('total_tokens', 0),
            total_tokens=self.total_tokens,
            max_total_tokens=self.config.max_total_tokens,
        )
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
        if 0 < self.config.max_total_tokens <= self.total_tokens:
            self._emit(
                "agent_limit_reached",
                component="agent",
                limit="max_total_tokens",
                input_tokens=self.last_input_tokens,
                total_tokens=self.total_tokens,
                max_total_tokens=self.config.max_total_tokens,
                remaining_tokens=0,
            )
            raise TotalTokenLimitExceeded(
                {
                    "role": "exit",
                    "content": "TotalTokenLimitExceeded",
                    "extra": {
                        "exit_status": "TotalTokenLimitExceeded",
                        "submission": "",
                        "input_tokens": self.last_input_tokens,
                        "total_tokens": self.total_tokens,
                        "max_total_tokens": self.config.max_total_tokens,
                    },
                }
            )
        return message

    @staticmethod
    def _fallback_token_estimate(value) -> int:
        serialized = json.dumps(value, ensure_ascii=False, default=str, separators=(',', ':'))
        return max(1, len(serialized.encode('utf-8')))

    def _estimate_input_tokens(self, messages: list[dict]) -> int:
        estimator = getattr(self.model, 'estimate_input_tokens', None)
        if callable(estimator):
            return max(1, int(estimator(messages)))
        prepared = [{k: v for k, v in message.items() if k != 'extra'} for message in messages]
        return self._fallback_token_estimate(prepared)

    def _record_usage(self, message: dict, *, fallback_prompt_tokens: int) -> None:
        extra = message.setdefault('extra', {})
        prompt_tokens = int(extra.get('prompt_tokens') or fallback_prompt_tokens or 0)
        completion_tokens = int(
            extra.get('completion_tokens') or self._fallback_token_estimate(message.get('content', ''))
        )
        total_tokens = int(extra.get('total_tokens') or (prompt_tokens + completion_tokens))
        extra.update(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self.prompt_tokens += prompt_tokens
        self.completion_tokens += completion_tokens
        self.total_tokens += total_tokens

    def _preflight_token_budget(self) -> int:
        estimated_input = self._estimate_input_tokens(self.messages)
        self.last_input_tokens = estimated_input
        context_percent = (
            estimated_input / self.config.max_input_tokens * 100
            if self.config.max_input_tokens > 0
            else 0.0
        )
        if 0 < self.config.max_input_tokens < estimated_input:
            self._emit(
                'agent_limit_reached',
                component='agent',
                limit='max_input_tokens',
                input_tokens=estimated_input,
                max_input_tokens=self.config.max_input_tokens,
                total_tokens=self.total_tokens,
                max_total_tokens=self.config.max_total_tokens,
                context_usage_percent=context_percent,
            )
            raise InputTokenLimitExceeded(
                {
                    'role': 'exit',
                    'content': 'InputTokenLimitExceeded',
                    'extra': {
                        'exit_status': 'InputTokenLimitExceeded',
                        'submission': '',
                        'input_tokens': estimated_input,
                        'max_input_tokens': self.config.max_input_tokens,
                        'total_tokens': self.total_tokens,
                    },
                }
            )

        output_budget = self.config.max_output_tokens
        remaining = 0
        if self.config.max_total_tokens > 0:
            remaining = self.config.max_total_tokens - self.total_tokens - estimated_input
            if remaining <= 0:
                self._emit(
                    'agent_limit_reached',
                    component='agent',
                    limit='max_total_tokens',
                    input_tokens=estimated_input,
                    total_tokens=self.total_tokens,
                    max_total_tokens=self.config.max_total_tokens,
                    remaining_tokens=max(0, self.config.max_total_tokens - self.total_tokens),
                    context_usage_percent=context_percent,
                )
                raise TotalTokenLimitExceeded(
                    {
                        'role': 'exit',
                        'content': 'TotalTokenLimitExceeded',
                        'extra': {
                            'exit_status': 'TotalTokenLimitExceeded',
                            'submission': '',
                            'input_tokens': estimated_input,
                            'total_tokens': self.total_tokens,
                            'max_total_tokens': self.config.max_total_tokens,
                        },
                    }
                )
            output_budget = min(output_budget, remaining) if output_budget > 0 else remaining

        self._emit(
            'model_preflight',
            component='model',
            input_tokens=estimated_input,
            total_tokens=self.total_tokens,
            max_input_tokens=self.config.max_input_tokens,
            max_total_tokens=self.config.max_total_tokens,
            context_usage_percent=context_percent,
            output_token_budget=output_budget,
        )
        return output_budget

    def execute_actions(self, message: dict) -> list[dict]:
        """Execute actions and report the observation transition."""
        actions = message.get("extra", {}).get("actions", [])
        if not actions:
            return []
        self.n_tool_calls += len(actions)

        if len(actions) == 1 and actions[0].get("tool") == "submit":
            answer = actions[0]["answer"].strip()
            outputs = [{"output": "Task submitted.", "returncode": 0, "exception_info": ""}]
            self._append_action_observations(message, actions, outputs)
            self._emit("agent_finish", component="agent", finish_reason="submit")
            raise Submitted(
                {
                    "role": "exit",
                    "content": answer,
                    "extra": {"exit_status": "Submitted", "submission": answer},
                }
            )

        action_hash = self._action_hash(actions)
        repeated_count = self.consecutive_repeated_actions + 1 if action_hash == self._last_action_hash else 1
        if 0 < self.config.max_repeated_actions < repeated_count:
            explanation = (
                f"Repeated PowerShell action blocked before execution after "
                f"{self.consecutive_repeated_actions} identical attempts."
            )
            outputs = [
                {
                    "output": "",
                    "returncode": -2,
                    "exception_info": explanation,
                    "extra": {"blocked": True, "guard": "repeated_action"},
                }
                for _ in actions
            ]
            self._append_action_observations(message, actions, outputs)
            self._raise_progress_limit(
                RepeatedActionExceeded,
                "RepeatedActionExceeded",
                "repeated_action",
                explanation,
            )

        outputs = [self.env.execute(action) for action in actions]
        result_hash = self._result_hash(outputs)
        warnings = []

        self._last_action_hash = action_hash
        self.consecutive_repeated_actions = repeated_count
        if repeated_count >= 2:
            warnings.append(
                f"The same PowerShell action has been requested {repeated_count} consecutive times. Change strategy."
            )

        if self._last_result_hash and result_hash == self._last_result_hash:
            self.no_progress_rounds += 1
            warnings.append(
                f"No new tool information was produced for {self.no_progress_rounds} consecutive round(s)."
            )
        else:
            self.no_progress_rounds = 0
        self._last_result_hash = result_hash

        if any(output.get("returncode") != 0 for output in outputs):
            self.consecutive_tool_failures += 1
            warnings.append(
                f"Tool execution has failed {self.consecutive_tool_failures} consecutive time(s)."
            )
        else:
            self.consecutive_tool_failures = 0

        added = self._append_action_observations(message, actions, outputs, warnings=warnings)
        if warnings:
            self._emit(
                "agent_progress_warning",
                component="agent",
                warnings=warnings,
                repeated_actions=self.consecutive_repeated_actions,
                no_progress_rounds=self.no_progress_rounds,
                consecutive_tool_failures=self.consecutive_tool_failures,
            )

        if (
            0 < self.config.max_consecutive_tool_failures <= self.consecutive_tool_failures
        ):
            self._raise_progress_limit(
                ConsecutiveToolFailuresExceeded,
                "ConsecutiveToolFailuresExceeded",
                "consecutive_tool_failures",
                f"Stopped after {self.consecutive_tool_failures} consecutive failed tool executions.",
            )
        if 0 < self.config.max_no_progress_rounds <= self.no_progress_rounds:
            self._raise_progress_limit(
                NoProgressExceeded,
                "NoProgressExceeded",
                "no_progress",
                f"Stopped after {self.no_progress_rounds} consecutive rounds without new tool information.",
            )
        return added

    @staticmethod
    def _action_hash(actions: list[dict]) -> str:
        normalized = [" ".join(action.get("command", "").strip().split()) for action in actions]
        payload = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _result_hash(outputs: list[dict]) -> str:
        fingerprints = []
        for output in outputs:
            extra = output.get("extra", {})
            output_digest = extra.get("output_sha256") or hashlib.sha256(
                str(output.get("output", "")).encode("utf-8")
            ).hexdigest()
            fingerprints.append(
                {
                    "returncode": output.get("returncode"),
                    "output_sha256": output_digest,
                    "exception_info": output.get("exception_info", ""),
                }
            )
        payload = json.dumps(fingerprints, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _append_action_observations(
        self,
        message: dict,
        actions: list[dict],
        outputs: list[dict],
        *,
        warnings: list[str] | None = None,
    ) -> list[dict]:
        observations = self.model.format_observation_messages(message, outputs, self.get_template_vars())
        if warnings:
            observations.append(
                self.model.format_message(
                    role="user",
                    content=(
                        "<agent-progress-warning>\n"
                        + "\n".join(f"- {warning}" for warning in warnings)
                        + "\nUse a different approach or call submit if the task is complete.\n"
                        "</agent-progress-warning>"
                    ),
                    extra={"agent_progress_warning": True},
                )
            )
        added = self.add_messages(*observations)
        self._emit(
            "agent_observation_added",
            component="agent",
            action_count=len(actions),
            observation_count=len(observations),
            message_count=len(self.messages),
        )
        return added

    def _raise_progress_limit(
        self,
        exception_class: type[LimitsExceeded],
        exit_status: str,
        limit: str,
        explanation: str,
    ) -> None:
        self._emit(
            "agent_limit_reached",
            component="agent",
            limit=limit,
            repeated_actions=self.consecutive_repeated_actions,
            no_progress_rounds=self.no_progress_rounds,
            consecutive_tool_failures=self.consecutive_tool_failures,
            explanation=explanation,
        )
        raise exception_class(
            {
                "role": "exit",
                "content": explanation,
                "extra": {
                    "exit_status": exit_status,
                    "submission": "",
                    "explanation": explanation,
                },
            }
        )

    def token_usage(self) -> dict[str, int]:
        return {
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'total_tokens': self.total_tokens,
            'last_input_tokens': self.last_input_tokens,
            'max_input_tokens': self.config.max_input_tokens,
            'max_total_tokens': self.config.max_total_tokens,
        }

    def serialize(self, *extra_dicts) -> dict:
        """Serialize the current linear history and task totals."""
        last_message = self.messages[-1] if self.messages else {}
        last_extra = self.last_result or last_message.get("extra", {})
        agent_data = {
            "schema_version": TRAJECTORY_SCHEMA_VERSION,
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
            "applied_skills": self.applied_skills,
            "trajectory_format": UPSTREAM_TRAJECTORY_FORMAT,
        }
        agent_data['info']['model_stats'].update(self.token_usage())
        agent_data['info']['progress_stats'] = {
            'consecutive_repeated_actions': self.consecutive_repeated_actions,
            'no_progress_rounds': self.no_progress_rounds,
            'consecutive_tool_failures': self.consecutive_tool_failures,
        }
        return validate_trajectory(
            recursive_merge(agent_data, self.model.serialize(), self.env.serialize(), *extra_dicts)
        )

    def save(self, path: Path | None, *extra_dicts) -> dict:
        """Save the serialized trajectory when a path is configured."""
        data = self.serialize(*extra_dicts)
        if path:
            write_trajectory(path, data)
        return data
