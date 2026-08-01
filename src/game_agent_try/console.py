"""Standalone conversational console for debugging the real GameAgent loop."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from game_agent_try.framework.agents.default import DefaultAgent
from game_agent_try.framework.models import get_model
from game_agent_try.logging import ExperimentLogger
from game_agent_try.mini import KitchenEnvironment, load_config
from game_agent_try.services.worker import (
    _capture_diff,
    _write_json,
    capture_task_baseline,
    prepare_run_config,
)
from game_agent_try.skills import build_skill_runtime


HELP = """Commands:
  /new [request]  save this task and start a fresh context
  /status         show task, turn, call, time, and change totals
  /diff           print the current project diff
  /help           show this help
  /exit           save artifacts and exit
"""


def load_env_file(path: Path) -> None:
    """Load a small dotenv-compatible subset without overriding the process."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)


def diff_summary(patch: str) -> dict[str, int]:
    files: set[str] = set()
    additions = 0
    deletions = 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                files.add(parts[3].removeprefix("b/"))
        elif line.startswith("+") and not line.startswith("+++"):
            additions += 1
        elif line.startswith("-") and not line.startswith("---"):
            deletions += 1
    return {"files": len(files), "additions": additions, "deletions": deletions}


class ConsoleRenderer:
    """Concise component-aware event renderer."""

    def __init__(self, stream: TextIO = sys.stdout, *, output_limit: int = 3000, output_lines: int = 24) -> None:
        self.stream = stream
        self.output_limit = output_limit
        self.output_lines = output_lines

    def write(self, text: str = "") -> None:
        print(text, file=self.stream, flush=True)

    def _bounded_output(self, value: Any) -> str:
        text = str(value or "").rstrip()
        lines = text.splitlines()
        if len(lines) > self.output_lines:
            text = "\n".join(lines[-self.output_lines :])
            text = f"鈥?{len(lines) - self.output_lines} earlier lines omitted\n{text}"
        if len(text) > self.output_limit:
            text = f"鈥?earlier output omitted\n{text[-self.output_limit:]}"
        return text

    def handle(self, record: dict[str, Any]) -> None:
        if record.get('event') == 'agent_limit_reached' and record.get('limit') in {
            'max_input_tokens',
            'max_total_tokens',
        }:
            input_tokens = record.get('input_tokens', 0)
            max_input = record.get('max_input_tokens', 0)
            total_tokens = record.get('total_tokens', 0)
            max_total = record.get('max_total_tokens', 0)
            self.write(
                f'[Agent]  TOKEN LIMIT {record.get("limit")} | input {input_tokens:,}/{max_input:,} | '
                f'total {total_tokens:,}/{max_total:,}'
            )
            return
        if record.get('event') == 'model_preflight':
            input_tokens = record.get('input_tokens', 0)
            max_input = record.get('max_input_tokens', 0)
            total_tokens = record.get('total_tokens', 0)
            max_total = record.get('max_total_tokens', 0)
            context_percent = record.get('context_usage_percent', 0.0)
            input_text = f'{input_tokens:,}/{max_input:,}' if max_input else f'{input_tokens:,}/unlimited'
            total_text = f'{total_tokens:,}/{max_total:,}' if max_total else f'{total_tokens:,}/unlimited'
            self.write(
                f'[Model]  request | input {input_text} | total {total_text} | context {context_percent:.1f}%'
            )
            return
        if record.get('event') == 'model_usage':
            prompt_tokens = record.get('prompt_tokens', 0)
            completion_tokens = record.get('completion_tokens', 0)
            total_tokens = record.get('total_tokens', 0)
            max_total = record.get('max_total_tokens', 0)
            self.write(
                f'[Model]  usage | input {prompt_tokens:,} + output {completion_tokens:,} | '
                f'total {total_tokens:,}/{max_total:,}'
            )
            return
        event = record["event"]
        if event == "turn_start":
            self.write(f"\n[Run]    Turn #{record['turn']} started")
        elif event == "agent_round_start":
            self.write(
                f"[Agent]  Round {record['round']} | {record.get('message_count', 0)} messages | requesting model"
            )
        elif event == "model_end":
            seconds = record.get("duration_ms", 0) / 1000
            actions = record.get("action_count", 0)
            outcome = f"{actions} tool action{'s' if actions != 1 else ''}" if actions else "message"
            self.write(f"[Model]  {record.get('model', 'model')} | {seconds:.1f}s | {outcome}")
            content = self._bounded_output(record.get("content"))
            if content:
                self.write(f"         {content}")
        elif event == "model_error":
            self.write(f"[Model]  ERROR {record.get('error_type', '')}: {record.get('error', '')}")
        elif event == "skill_not_found":
            self.write("[Skill]  no Skill matched")
        elif event == "skill_search_start":
            self.write(f"[Skill]  searching {record.get('query', 'available Skills')}")
        elif event == "skill_matched":
            self.write(f"[Skill]  matched {record.get('skill_name', record.get('skill_id', 'Skill'))}")
        elif event == "skill_apply_start":
            self.write(f"[Skill]  applying {record.get('skill_name', record.get('skill_id', 'Skill'))}")
        elif event == "skill_apply_end":
            seconds = record.get("duration_ms", 0) / 1000
            self.write(f"[Skill]  applied {record.get('skill_name', record.get('skill_id', 'Skill'))} | {seconds:.1f}s")
        elif event == "skill_apply_failed":
            self.write(
                f"[Skill]  ERROR {record.get('skill_name', record.get('skill_id', 'Skill'))}: "
                f"{record.get('error', '')}"
            )
        elif event == "tool_start":
            self.write(f"[Env]    {record.get('tool', 'powershell')}: {record.get('command', '')}")
        elif event == "tool_end":
            seconds = record.get("duration_ms", 0) / 1000
            output = self._bounded_output(record.get("output"))
            exception = self._bounded_output(record.get("exception_info"))
            self.write(f"         exit {record.get('returncode', -1)} | {seconds:.1f}s")
            if output:
                self.write("\n".join(f"         {line}" for line in output.splitlines()))
            if exception:
                self.write("\n".join(f"         ERROR {line}" for line in exception.splitlines()))
        elif event == "agent_observation_added":
            self.write(f"[Agent]  observation appended | {record.get('message_count', 0)} messages")
        elif event == "agent_progress_warning":
            self.write(
                f"[Agent]  progress warning | repeated {record.get('repeated_actions', 0)} | "
                f"no progress {record.get('no_progress_rounds', 0)} | "
                f"failures {record.get('consecutive_tool_failures', 0)}"
            )
        elif event == "agent_limit_reached":
            self.write(
                f"[Agent]  limit reached: {record.get('limit')} after {record.get('turn_model_calls', 0)} calls"
            )
        elif event == "validation_start":
            self.write(f"[Verify] start {record.get('validator', 'validator')}")
        elif event == "validation_end":
            self.write(f"[Verify] {record.get('status', 'finished')} {record.get('validator', 'validator')}")
        elif event == "turn_end":
            self.write(f"[Run]    Turn #{record['turn']} {record.get('status', 'completed')}")

    def turn_summary(self, task: "ConsoleTask", result: dict[str, Any]) -> None:
        summary = task.current_diff_summary()
        answer = result.get("submission") or result.get("error") or result.get("exit_status", "No final answer")
        elapsed = time.time() - task.started_at
        self.write(
            f'Tokens {task.agent.prompt_tokens:,} input + {task.agent.completion_tokens:,} output '
            f'= {task.agent.total_tokens:,}/{task.agent.config.max_total_tokens:,}'
        )
        self.write(f"\n鉁?{answer}" if result.get("exit_status") == "Submitted" else f"\n! {answer}")
        self.write(
            f"Calls  {task.agent.n_calls} model 路 {task.agent.n_tool_calls} tools\n"
            f"Time   {elapsed:.1f}s\n"
            f"Files  {summary['files']} changed 路 +{summary['additions']} -{summary['deletions']}\n"
            f"Diff   {task.artifact_dir / 'diff.patch'}"
        )


class ConsoleTask:
    """One persistent multi-turn Agent context and its artifacts."""

    def __init__(
        self,
        config_path: Path,
        *,
        project_path: Path | None = None,
        artifact_root: Path = Path("artifacts/console"),
        task_id: str | None = None,
        renderer: ConsoleRenderer | None = None,
        model_factory: Callable[[str, dict], Any] = get_model,
    ) -> None:
        source_config = load_config(config_path.resolve())
        self.project_path = (project_path or Path(source_config["environment"]["cwd"])).resolve()
        if not self.project_path.is_dir():
            raise FileNotFoundError(f"Project directory does not exist: {self.project_path}")
        if not (self.project_path / "ProjectSettings" / "ProjectVersion.txt").is_file():
            raise ValueError(f"Not a Unity project: {self.project_path}")

        self.task_id = task_id or uuid.uuid4().hex[:12]
        self.artifact_dir = artifact_root.resolve() / self.task_id
        self.artifact_dir.mkdir(parents=True, exist_ok=False)
        self.workspace_baseline = capture_task_baseline(
            self.project_path,
            self.artifact_dir / "workspace-baseline.json",
            exclude_paths=(self.artifact_dir,),
        )
        resolved_config_path = prepare_run_config(config_path.resolve(), self.artifact_dir, self.project_path)
        self.config = load_config(resolved_config_path)
        self.renderer = renderer or ConsoleRenderer()
        experiment = self.config["experiment"]
        self.logger = ExperimentLogger(
            self.artifact_dir / "events.jsonl",
            run_id=self.task_id,
            config_id=experiment["config_id"],
            schema_version="game-agent-jsonl-v3",
            context={"task_id": self.task_id},
            listeners=[self.renderer.handle],
        )

        model_config = dict(self.config["model"])
        model_name = model_config.pop("model_name")
        self.model = model_factory(model_name, model_config)
        environment_config = dict(self.config["environment"])
        environment_config.update(
            telemetry_path=str(self.artifact_dir / "events.jsonl"),
            run_id=self.task_id,
            config_id=experiment["config_id"],
            logger=self.logger,
        )
        self.environment = KitchenEnvironment(**environment_config)
        agent_config = dict(self.config["agent"])
        context_config = dict(self.config.get("context", {}))
        configured_graph = str(context_config.get("graph_path", "")).strip()
        if configured_graph and not Path(configured_graph).is_absolute():
            context_config["graph_path"] = str(
                (resolved_config_path.parent.parent / configured_graph).resolve()
            )
        aci_config = dict(self.config.get("aci", {}))
        if not aci_config.get("editor_path"):
            aci_config["editor_path"] = str(
                self.config.get("validation", {}).get("editor_path", "")
            )
        agent_config.update(
            output_path=self.artifact_dir / "trajectory.json",
            event_sink=self.logger.emit,
            event_context_sink=self.logger.set_context,
            max_input_tokens=experiment["max_input_tokens"],
            max_output_tokens=experiment["max_output_tokens"],
            max_total_tokens=experiment["max_total_tokens"],
            context=context_config,
            aci=aci_config,
            skill_runtime=build_skill_runtime(
                self.config,
                self.logger,
                config_path=resolved_config_path,
            ),
        )
        self.agent = DefaultAgent(self.model, self.environment, **agent_config)
        self.started_at = time.time()
        self.last_result: dict[str, Any] = {}
        self.closed = False
        self.logger.emit(
            "task_start",
            component="run",
            turn=0,
            round=0,
            project_path=str(self.project_path),
            model=model_name,
        )

    def run_turn(self, request: str) -> dict[str, Any]:
        turn = self.agent.turn + 1
        self.logger.set_context(turn=turn, round=0)
        self.logger.emit("turn_start", component="run", request=request)
        try:
            result = self.agent.run_turn(request)
            status = "completed" if result.get("exit_status") == "Submitted" else "stopped"
            self.last_result = dict(result)
            self.logger.set_context(turn=self.agent.turn, round=self.agent.round)
            self.logger.emit("turn_end", component="run", status=status, **result)
            self._write_artifacts(status="active")
            self.renderer.turn_summary(self, result)
            return result
        except BaseException as error:
            self.last_result = {
                "exit_status": type(error).__name__,
                "submission": "",
                "error": str(error),
            }
            self.logger.set_context(turn=self.agent.turn, round=self.agent.round)
            self.logger.emit(
                "turn_end",
                component="run",
                status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                error_type=type(error).__name__,
                error=str(error),
            )
            self._write_artifacts(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed")
            raise

    def _write_artifacts(self, *, status: str) -> None:
        self.agent.save(
            self.artifact_dir / "trajectory.json",
            {
                "info": {
                    "task_id": self.task_id,
                    "turn_count": self.agent.turn,
                    "project_path": str(self.project_path),
                }
            },
        )
        _capture_diff(self.project_path, self.artifact_dir / "diff.patch", self.workspace_baseline)
        _write_json(
            self.artifact_dir / "result.json",
            {
                "task_id": self.task_id,
                "status": status,
                "turn_count": self.agent.turn,
                "model_calls": self.agent.n_calls,
                "tool_calls": self.agent.n_tool_calls,
                "model_cost": self.agent.cost,
                'token_usage': self.agent.token_usage(),
                **self.last_result,
            },
        )

    def current_diff(self) -> str:
        _capture_diff(self.project_path, self.artifact_dir / "diff.patch", self.workspace_baseline)
        return (self.artifact_dir / "diff.patch").read_text(encoding="utf-8")

    def current_diff_summary(self) -> dict[str, int]:
        return diff_summary(self.current_diff())

    def status_text(self) -> str:
        summary = self.current_diff_summary()
        token_status = (
            f'Tokens {self.agent.prompt_tokens:,} input + {self.agent.completion_tokens:,} output '
            f'= {self.agent.total_tokens:,}/{self.agent.config.max_total_tokens:,}\n'
        )
        return (
            token_status
            +
            f"Task   {self.task_id}\n"
            f"Turn   {self.agent.turn}\n"
            f"Calls  {self.agent.n_calls} model 路 {self.agent.n_tool_calls} tools\n"
            f"Cost   ${self.agent.cost:.4f}\n"
            f"Time   {time.time() - self.started_at:.1f}s\n"
            f"Files  {summary['files']} changed 路 +{summary['additions']} -{summary['deletions']}"
        )

    def close(self, *, status: str = "closed") -> None:
        if self.closed:
            return
        self.logger.set_context(turn=self.agent.turn, round=self.agent.round)
        self.logger.emit("task_end", component="run", status=status)
        self._write_artifacts(status=status)
        self.closed = True


class ConsoleSession:
    """Command dispatcher for multiple tasks in one terminal process."""

    def __init__(
        self,
        config_path: Path,
        *,
        project_path: Path | None = None,
        artifact_root: Path = Path("artifacts/console"),
        renderer: ConsoleRenderer | None = None,
        task_factory: Callable[..., ConsoleTask] = ConsoleTask,
    ) -> None:
        self.config_path = config_path
        self.project_path = project_path
        self.artifact_root = artifact_root
        self.renderer = renderer or ConsoleRenderer()
        self.task_factory = task_factory
        self.task = self._new_task()

    def _new_task(self) -> ConsoleTask:
        return self.task_factory(
            self.config_path,
            project_path=self.project_path,
            artifact_root=self.artifact_root,
            renderer=self.renderer,
        )

    def handle(self, line: str) -> bool:
        text = line.strip()
        if not text:
            return True
        command, _, argument = text.partition(" ")
        if command == "/exit":
            self.task.close()
            return False
        if command == "/help":
            self.renderer.write(HELP.rstrip())
            return True
        if command == "/status":
            self.renderer.write(self.task.status_text())
            return True
        if command == "/diff":
            patch = self.task.current_diff().rstrip()
            self.renderer.write(patch or "(no project changes)")
            return True
        if command == "/new":
            next_task = self._new_task()
            self.task.close()
            self.task = next_task
            if argument.strip():
                self.task.run_turn(argument.strip())
            return True
        if command.startswith("/"):
            self.renderer.write(f"Unknown command: {command}\n{HELP.rstrip()}")
            return True
        self.task.run_turn(text)
        return True

    def close(self, *, status: str = "closed") -> None:
        self.task.close(status=status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone conversational SkillGameAgent debugger")
    parser.add_argument("--config", default="configs/kitchen_chaos.json")
    parser.add_argument("--project", help="Unity project path; defaults to the selected config")
    parser.add_argument("--artifacts", default="artifacts/console")
    parser.add_argument("--task", help="Run this request before opening the prompt")
    parser.add_argument("--once", action="store_true", help="Exit after --task finishes")
    parser.add_argument("--env-file", default=".env", help="Environment file loaded without overriding existing values")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path.cwd()
    load_env_file((root / args.env_file).resolve())
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    project_path = Path(args.project).resolve() if args.project else None
    artifact_root = Path(args.artifacts)
    if not artifact_root.is_absolute():
        artifact_root = root / artifact_root

    renderer = ConsoleRenderer()
    session = ConsoleSession(
        config_path.resolve(),
        project_path=project_path,
        artifact_root=artifact_root.resolve(),
        renderer=renderer,
    )
    config = session.task.config
    renderer.write(
        "GameAgent CLI\n"
        f"Project  {session.task.project_path}\n"
        f"Model    {config['model']['model_name']}\n"
        f"Artifacts {session.task.artifact_dir}\n"
        "Type /help for commands."
    )

    try:
        if args.task:
            session.handle(args.task)
            if args.once:
                session.close()
                return
        while True:
            try:
                line = input("\nYou > ")
            except EOFError:
                break
            except KeyboardInterrupt:
                renderer.write("\nInterrupted. Saving task and exiting.")
                break
            try:
                if not session.handle(line):
                    return
            except KeyboardInterrupt:
                renderer.write("\n[Run]    Turn interrupted; artifacts saved.")
            except Exception as error:
                renderer.write(f"\n[Run]    ERROR {type(error).__name__}: {error}")
    finally:
        session.close(status="closed")


if __name__ == "__main__":
    main()
