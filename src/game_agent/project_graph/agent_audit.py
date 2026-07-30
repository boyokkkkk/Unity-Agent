from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from game_agent.console import load_env_file
from game_agent.mini import load_config, run as run_agent
from game_agent.services.worker import _capture_diff, capture_task_baseline
from game_agent.workspace import create_task_workspace

from .evaluation import LocalizationTask, LocalizationTaskSet, precision_at_k, recall_at_k
from .retrieval import LocalizationRetriever
from .schema import ProjectGraph


AGENT_AUDIT_SCHEMA_VERSION = "game-agent-project-graph-agent-audit-v1"
GRAPH_QUERY_MARKER = "game-agent-graph"
FILE_PATTERN = re.compile(r"(?:Assets|Packages)[\\/][^\s\"'`,;\]\}]+\.cs", re.IGNORECASE)


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _normalize(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _event_command(event: dict[str, Any]) -> str:
    return str(event.get("command", ""))


def _extract_submission_scope(submission: str) -> dict[str, list[str]]:
    decoded: dict[str, Any] = {}
    starts = [index for index, character in enumerate(submission) if character == "{"]
    ends = [index for index, character in enumerate(submission) if character == "}"]
    for start in starts:
        for end in reversed(ends):
            if end <= start:
                continue
            try:
                candidate = json.loads(submission[start:end + 1])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                decoded = candidate
                break
        if decoded:
            break
    files = [str(value) for value in decoded.get("files", []) if isinstance(value, str)]
    if not files:
        files = FILE_PATTERN.findall(submission)
    return {
        "files": files,
        "game_objects": [
            str(value) for value in decoded.get("game_objects", []) if isinstance(value, str)
        ],
        "assets": [
            str(value) for value in decoded.get("assets", []) if isinstance(value, str)
        ],
        "dependency_paths": [
            str(value) for value in decoded.get("dependency_paths", [])
        ],
        "graph_evidence": [
            str(value) for value in decoded.get("graph_evidence", [])
        ],
    }


class GraphUsageAnalyzer:
    def analyze(
        self,
        *,
        events: list[dict[str, Any]],
        submission: str,
        task: LocalizationTask,
        graph_result: dict[str, Any],
        diff_text: str = "",
    ) -> dict[str, Any]:
        tool_starts = [event for event in events if event.get("event") == "tool_start"]
        graph_starts = [
            event for event in tool_starts
            if GRAPH_QUERY_MARKER in _event_command(event).casefold()
            and " query " in f" {_event_command(event).casefold()} "
        ]
        graph_sequences = [int(event.get("seq", 0)) for event in graph_starts]
        first_graph_seq = min(graph_sequences, default=None)
        graph_ends = [
            event for event in events
            if event.get("event") == "tool_end"
            and GRAPH_QUERY_MARKER in _event_command(event).casefold()
            and " query " in f" {_event_command(event).casefold()} "
        ]
        successful_graph_calls = sum(
            int(event.get("returncode", 1)) == 0 for event in graph_ends
        )
        manual_starts = [
            event for event in tool_starts
            if event not in graph_starts
            and str(event.get("command_category", "")) in {"search", "read"}
        ]
        first_manual_seq = min(
            (int(event.get("seq", 0)) for event in manual_starts),
            default=None,
        )
        opened_after_graph: list[str] = []
        for event in tool_starts:
            if first_graph_seq is None or int(event.get("seq", 0)) <= first_graph_seq:
                continue
            opened_after_graph.extend(str(value) for value in event.get("accessed_files", []))
        recommended_files = [
            str(item.get("path", ""))
            for item in graph_result.get("files", [])
            if item.get("path")
        ]
        recommended_normalized = {_normalize(value) for value in recommended_files}
        adopted_files = sorted({
            value for value in opened_after_graph
            if _normalize(value) in recommended_normalized
        })
        scope = _extract_submission_scope(submission)
        file_rank = [_normalize(value) for value in scope["files"]]
        gold_files = [_normalize(value) for value in task.gold_files]
        final_file_recall = recall_at_k(file_rank, gold_files, max(len(file_rank), 1))
        final_file_precision = precision_at_k(file_rank, gold_files, max(len(file_rank), 1))
        final_objects = [_normalize(value) for value in scope["game_objects"]]
        final_assets = [_normalize(value) for value in scope["assets"]]
        object_recall = recall_at_k(
            final_objects,
            task.gold_game_objects,
            max(len(final_objects), 1),
            contains=True,
        )
        asset_recall = recall_at_k(
            final_assets,
            task.gold_assets,
            max(len(final_assets), 1),
        )
        graph_before_manual = (
            first_graph_seq is not None
            and (first_manual_seq is None or first_graph_seq < first_manual_seq)
        )
        no_source_changes = not diff_text.strip()
        correct = (
            bool(graph_starts)
            and successful_graph_calls == len(graph_starts)
            and graph_before_manual
            and final_file_recall >= 0.5
            and no_source_changes
        )
        return {
            "schema_version": AGENT_AUDIT_SCHEMA_VERSION,
            "correctly_applied": correct,
            "graph_tool": {
                "invocations": len(graph_starts),
                "successful_invocations": successful_graph_calls,
                "first_graph_seq": first_graph_seq,
                "first_manual_navigation_seq": first_manual_seq,
                "graph_before_manual_navigation": graph_before_manual,
            },
            "adoption": {
                "recommended_files": recommended_files,
                "opened_after_graph": opened_after_graph,
                "adopted_recommended_files": adopted_files,
                "recommended_file_adoption_rate": (
                    len(adopted_files) / len(recommended_files)
                    if recommended_files else 0.0
                ),
            },
            "final_scope": scope,
            "metrics": {
                "file_recall": final_file_recall,
                "file_precision": final_file_precision,
                "gameobject_recall": object_recall,
                "asset_recall": asset_recall,
            },
            "safety": {
                "source_changes": bool(diff_text.strip()),
                "no_source_changes": no_source_changes,
            },
        }


def run_agent_graph_audit(
    *,
    source_project: Path,
    graph_path: Path,
    tasks_path: Path,
    task_id: str,
    config_path: Path,
    artifact_dir: Path,
    env_file: Path | None = None,
) -> dict[str, Any]:
    source_project = source_project.resolve()
    graph_path = graph_path.resolve()
    artifact_dir = artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=False)
    if env_file:
        load_env_file(env_file.resolve())
    task_set = LocalizationTaskSet.model_validate_json(
        tasks_path.read_text(encoding="utf-8")
    )
    task = next((item for item in task_set.tasks if item.id == task_id), None)
    if task is None:
        raise ValueError(f"Unknown localization task: {task_id}")
    run_id = artifact_dir.name or uuid.uuid4().hex[:12]
    started = time.monotonic()
    lease = create_task_workspace(
        source_project,
        artifact_dir / "workspace",
        mode="copy",
    )
    try:
        project = lease.project_path
        baseline = capture_task_baseline(
            project,
            artifact_dir / "workspace-baseline.json",
            exclude_paths=(artifact_dir,),
        )
        if baseline is None:
            raise RuntimeError("Unable to capture Agent audit workspace baseline")
        config = json.loads(json.dumps(load_config(config_path)))
        config["experiment"].update(
            config_id="unity-project-graph-agent-audit-v1",
            target_project=str(project),
            max_rounds=15,
            max_total_tokens=32_768,
        )
        config["environment"]["cwd"] = str(project)
        config["agent"].update(
            step_limit=15,
            max_no_progress_rounds=2,
            max_repeated_actions=2,
        )
        config.setdefault("skills", {}).update(enabled=False, paths=[])
        config.setdefault("validation", {})["enabled"] = False
        config["logging"]["events_path"] = str(artifact_dir / "events.jsonl")
        config["logging"]["trajectory_path"] = str(artifact_dir / "trajectory.json")
        prepared_config = artifact_dir / "config.json"
        _atomic_json(prepared_config, config)

        executable = (
            Path(__file__).resolve().parents[3]
            / ".venv"
            / "Scripts"
            / "game-agent-graph.exe"
        )
        query_output = artifact_dir / "agent-graph-query.json"
        command = (
            f"& '{executable}' query --graph '{graph_path}' --project '{project}' "
            f"--variant A2 --limit 10 --query '{task.query}' "
            f"--output '{query_output}'"
        )
        prompt = (
            "这是影响范围定位评测，不是代码修改任务。禁止修改任何文件，也不要运行 Unity。\n"
            "必须先运行下面的项目图查询命令，再根据返回的 files、game_objects、assets 和 "
            "dependency_paths，只读取必要的候选 C# 文件进行核验：\n\n"
            f"{command}\n\n"
            f"需求：{task.query}\n\n"
            "完成后调用 submit。提交内容必须只包含一个合法 JSON 对象，格式："
            '{"files":[],"game_objects":[],"assets":[],"dependency_paths":[],'
            '"graph_evidence":[]}。所有路径使用 Unity 项目相对路径；'
            "graph_evidence 说明采用了哪些图节点或边。"
        )
        result = run_agent(prompt, prepared_config, run_id=run_id)
        _atomic_json(artifact_dir / "agent-result.json", result)
        diff_path = artifact_dir / "diff.patch"
        _capture_diff(project, diff_path, baseline)
        diff_text = diff_path.read_text(encoding="utf-8", errors="replace")
        events = [
            json.loads(line)
            for line in (artifact_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        graph = ProjectGraph.load(graph_path)
        graph_result = LocalizationRetriever(graph, project).retrieve(
            task.query,
            "A2",
            limit=10,
        ).to_dict()
        audit = GraphUsageAnalyzer().analyze(
            events=events,
            submission=str(result.get("submission", "")),
            task=task,
            graph_result=graph_result,
            diff_text=diff_text,
        )
        report = {
            "schema_version": AGENT_AUDIT_SCHEMA_VERSION,
            "run_id": run_id,
            "task_id": task.id,
            "duration_ms": round((time.monotonic() - started) * 1000),
            "agent": {
                "exit_status": result.get("exit_status", ""),
                "submission": result.get("submission", ""),
                "token_usage": result.get("token_usage", {}),
            },
            "audit": audit,
            "artifacts": {
                "events": "events.jsonl",
                "trajectory": "trajectory.json",
                "graph_query": "agent-graph-query.json",
                "diff": "diff.patch",
            },
        }
        _atomic_json(artifact_dir / "agent-graph-audit.json", report)
        return report
    finally:
        lease.close()
