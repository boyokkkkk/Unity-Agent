from __future__ import annotations

import csv
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from game_agent_try.registry import COMPONENTS

from .adapter import register_builtin_adapters
from .schemas import BenchmarkManifest, RESULT_SCHEMA_VERSION


PROGRESS_SCHEMA_VERSION = "game-agent-benchmark-progress-v1"
SUMMARY_SCHEMA_VERSION = "game-agent-benchmark-summary-v1"


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _case_id(payload: dict[str, Any]) -> str:
    payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class BenchmarkRunner:
    def __init__(self, manifest: BenchmarkManifest, manifest_path: Path, *, output_dir: Path | None = None):
        self.manifest = manifest
        self.manifest_path = manifest_path.resolve()
        configured_output = Path(manifest.output_dir)
        if not configured_output.is_absolute():
            configured_output = self.manifest_path.parent / configured_output
        self.output_dir = (output_dir or configured_output / manifest.benchmark_id).resolve()
        self.progress_path = self.output_dir / "progress.json"
        register_builtin_adapters()

    @classmethod
    def from_path(cls, path: Path, *, output_dir: Path | None = None) -> "BenchmarkRunner":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(BenchmarkManifest.model_validate(data), path, output_dir=output_dir)

    def expand_cases(self) -> list[dict[str, Any]]:
        root = self.manifest_path.parent
        cases = []
        for task in self.manifest.tasks:
            project = Path(task.project_path)
            config = Path(task.config_path)
            project = project if project.is_absolute() else (root / project).resolve()
            config = config if config.is_absolute() else (root / config).resolve()
            for model in self.manifest.matrix.models:
                for skill in self.manifest.matrix.skills:
                    resolved_skill = skill.model_dump()
                    resolved_skill["paths"] = [
                        str(path if path.is_absolute() else (root / path).resolve())
                        for value in skill.paths for path in [Path(value)]
                    ]
                    for seed in self.manifest.matrix.seeds:
                        identifier = _case_id({
                            "benchmark_id": self.manifest.benchmark_id,
                            "task_id": task.id,
                            "task": task.task,
                            "project_path": str(project),
                            "config_path": str(config),
                            "model": model.model_dump(mode="json"),
                            "skill": resolved_skill,
                            "seed": seed,
                        })
                        cases.append(
                            {
                                "case_id": identifier,
                                "task_id": task.id,
                                "task": task.task,
                                "project_path": str(project),
                                "config_path": str(config),
                                "model": model.model_dump(),
                                "skill": resolved_skill,
                                "seed": seed,
                                "axes": {"model": model.name, "skill": skill.name, "seed": seed},
                                "tags": task.tags,
                            }
                        )
        return cases

    def run(
        self,
        *,
        resume: bool | None = None,
        max_workers: int | None = None,
    ) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        resume = self.manifest.execution.resume if resume is None else resume
        previous = self._load_progress() if resume else {}
        cases = self.expand_cases()
        current_ids = {case["case_id"] for case in cases}
        results: dict[str, dict[str, Any]] = {
            case_id: result for case_id, result in previous.get("results", {}).items()
            if case_id in current_ids
        }
        pending = []
        for case in cases:
            existing = results.get(case["case_id"])
            if existing and existing.get("success"):
                continue
            if existing and not self.manifest.execution.retry_failed_on_resume:
                continue
            pending.append(case)

        workers = max_workers or self.manifest.execution.max_workers
        started = time.time()
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="unity-benchmark") as executor:
            futures = {executor.submit(self._run_with_retries, case, results.get(case["case_id"])): case for case in pending}
            for future in as_completed(futures):
                case = futures[future]
                try:
                    results[case["case_id"]] = future.result()
                except BaseException as exc:
                    results[case["case_id"]] = self._exception_result(case, exc)
                self._save_progress(cases, results, started)

        ordered = [results[case["case_id"]] for case in cases if case["case_id"] in results]
        summary = aggregate_results(ordered)
        final = {
            "schema_version": SUMMARY_SCHEMA_VERSION,
            "benchmark_id": self.manifest.benchmark_id,
            "adapter": self.manifest.adapter,
            "planned_cases": len(cases),
            "completed_cases": len(ordered),
            "duration_seconds": time.time() - started,
            "metrics": summary,
            "results": ordered,
        }
        _atomic_json(self.output_dir / "results.json", final)
        _atomic_json(self.output_dir / "summary.json", {key: value for key, value in final.items() if key != "results"})
        self._write_csv(ordered)
        return final

    def _run_with_retries(self, case: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any]:
        adapter = COMPONENTS.create("benchmark_adapter", self.manifest.adapter)
        attempts = list((existing or {}).get("attempts", []))
        case_root = self.output_dir / "cases" / case["case_id"]
        disk_attempts = [
            int(path.name.removeprefix("attempt-"))
            for path in case_root.glob("attempt-*")
            if path.is_dir() and path.name.removeprefix("attempt-").isdigit()
        ] if case_root.is_dir() else []
        first_attempt = max([len(attempts), *disk_attempts], default=0) + 1
        final: dict[str, Any] = {}
        for attempt in range(first_attempt, first_attempt + self.manifest.execution.retries + 1):
            attempt_dir = self.output_dir / "cases" / case["case_id"] / f"attempt-{attempt:03d}"
            try:
                final = adapter.run_case(case, attempt_dir, attempt)
            except BaseException as exc:
                final = self._exception_result(case, exc, attempt=attempt, artifact_dir=attempt_dir)
            attempts.append({
                key: final.get(key)
                for key in (
                    "attempt", "success", "exit_status", "error", "rate_limited", "artifact_dir",
                    "cost", "duration_seconds", "model_calls", "tool_calls", "rounds", "token_usage",
                )
            })
            if final.get("success"):
                break
        final["attempts"] = attempts
        final["cost"] = sum(float(item.get("cost", 0.0) or 0.0) for item in attempts)
        final["duration_seconds"] = sum(float(item.get("duration_seconds", 0.0) or 0.0) for item in attempts)
        final["model_calls"] = sum(int(item.get("model_calls", 0) or 0) for item in attempts)
        final["tool_calls"] = sum(int(item.get("tool_calls", 0) or 0) for item in attempts)
        final["rounds"] = sum(int(item.get("rounds", 0) or 0) for item in attempts)
        token_keys = {key for item in attempts for key in (item.get("token_usage") or {})}
        final["token_usage"] = {
            key: sum(int((item.get("token_usage") or {}).get(key, 0) or 0) for item in attempts)
            for key in token_keys
        }
        return final

    def _load_progress(self) -> dict[str, Any]:
        if not self.progress_path.is_file():
            return {}
        data = json.loads(self.progress_path.read_text(encoding="utf-8"))
        if data.get("schema_version") != PROGRESS_SCHEMA_VERSION:
            raise ValueError("Unsupported benchmark progress schema")
        if data.get("benchmark_id") != self.manifest.benchmark_id:
            raise ValueError("Progress file belongs to a different benchmark")
        return data

    def _save_progress(self, cases: list[dict], results: dict[str, dict], started: float) -> None:
        _atomic_json(
            self.progress_path,
            {
                "schema_version": PROGRESS_SCHEMA_VERSION,
                "benchmark_id": self.manifest.benchmark_id,
                "planned_cases": len(cases),
                "completed_cases": len(results),
                "elapsed_seconds": time.time() - started,
                "results": results,
            },
        )

    @staticmethod
    def _exception_result(
        case: dict[str, Any], exc: BaseException, *, attempt: int = 0, artifact_dir: Path | None = None
    ) -> dict[str, Any]:
        error = f"{type(exc).__name__}: {exc}"
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "case_id": case["case_id"], "task_id": case["task_id"], "attempt": attempt,
            "axes": case["axes"], "success": False, "agent_success": False,
            "verified_success": False, "validation_status": "missing", "exit_status": type(exc).__name__,
            "submission": "", "error": error,
            "rate_limited": any(marker in error.casefold() for marker in ("rate limit", "rate_limit", "429")),
            "duration_seconds": 0.0, "cost": 0.0, "model_calls": 0, "tool_calls": 0,
            "rounds": 0, "token_usage": {}, "validation": {},
            "artifact_dir": str(artifact_dir or ""),
        }

    def _write_csv(self, results: list[dict[str, Any]]) -> None:
        fields = [
            "case_id", "task_id", "model", "skill", "seed", "success", "agent_success",
            "verified_success", "validation_status", "attempt", "exit_status", "cost",
            "model_calls", "tool_calls", "rounds", "duration_seconds", "total_tokens", "artifact_dir",
        ]
        with (self.output_dir / "results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for result in results:
                writer.writerow({
                    **{key: result.get(key, "") for key in fields},
                    **result.get("axes", {}),
                    "total_tokens": result.get("token_usage", {}).get("total_tokens", 0),
                })


def _metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    count = len(results)
    success = sum(bool(result.get("success")) for result in results)
    agent_success = sum(bool(result.get("agent_success")) for result in results)
    verified = sum(bool(result.get("verified_success")) for result in results)
    validation_counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("validation_status", "missing"))
        validation_counts[status] = validation_counts.get(status, 0) + 1
    cost = sum(float(result.get("cost", 0.0) or 0.0) for result in results)
    calls = sum(int(result.get("model_calls", 0) or 0) for result in results)
    rounds = sum(int(result.get("rounds", 0) or 0) for result in results)
    duration = sum(float(result.get("duration_seconds", 0.0) or 0.0) for result in results)
    tokens = sum(int(result.get("token_usage", {}).get("total_tokens", 0) or 0) for result in results)
    return {
        "cases": count,
        "successes": success,
        "success_rate": success / count if count else 0.0,
        "agent_successes": agent_success,
        "agent_success_rate": agent_success / count if count else 0.0,
        "verified_successes": verified,
        "verified_success_rate": verified / count if count else 0.0,
        "validation": validation_counts,
        "cost": {"total": cost, "mean": cost / count if count else 0.0},
        "model_calls": {"total": calls, "mean": calls / count if count else 0.0},
        "rounds": {"total": rounds, "mean": rounds / count if count else 0.0},
        "duration_seconds": {"total": duration, "mean": duration / count if count else 0.0},
        "tokens": {"total": tokens, "mean": tokens / count if count else 0.0},
    }


def aggregate_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {
        "model": {}, "skill": {}, "seed": {}, "combination": {}
    }
    for result in results:
        axes = result.get("axes", {})
        for axis in ("model", "skill", "seed"):
            key = str(axes.get(axis, ""))
            grouped[axis].setdefault(key, []).append(result)
        combination = f"{axes.get('model', '')}|{axes.get('skill', '')}|{axes.get('seed', '')}"
        grouped["combination"].setdefault(combination, []).append(result)
    return {
        "overall": _metrics(results),
        **{
            f"by_{axis}": {key: _metrics(items) for key, items in sorted(groups.items())}
            for axis, groups in grouped.items()
        },
    }
