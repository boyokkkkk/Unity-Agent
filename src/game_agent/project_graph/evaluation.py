from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .retrieval import LocalizationResult, LocalizationRetriever
from .schema import ProjectGraph
from .statistics import infer_localization_statistics


LOCALIZATION_TASK_SCHEMA = "game-agent-localization-tasks-v1"
LOCALIZATION_RESULT_SCHEMA = "game-agent-localization-evaluation-v1"


class GoldDependencyPath(BaseModel):
    source_contains: str = ""
    target_contains: str = ""
    edge_kinds: list[str] = Field(default_factory=list)


class LocalizationTask(BaseModel):
    id: str
    query: str
    gold_files: list[str] = Field(default_factory=list)
    gold_game_objects: list[str] = Field(default_factory=list)
    gold_assets: list[str] = Field(default_factory=list)
    gold_dependency_paths: list[GoldDependencyPath] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in value
        ):
            raise ValueError("task id contains unsupported characters")
        return value


class LocalizationTaskSet(BaseModel):
    schema_version: Literal["game-agent-localization-tasks-v1"] = LOCALIZATION_TASK_SCHEMA
    project_path: str
    tasks: list[LocalizationTask]
    ks: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])

    @field_validator("tasks", "ks")
    @classmethod
    def require_non_empty(cls, value: list) -> list:
        if not value:
            raise ValueError("tasks and ks must be non-empty")
        return value


class LocalizationEvaluator:
    def __init__(self, graph: ProjectGraph, task_set: LocalizationTaskSet):
        self.graph = graph
        self.task_set = task_set
        self.retriever = LocalizationRetriever(graph, Path(task_set.project_path))

    @classmethod
    def from_paths(cls, graph_path: Path, tasks_path: Path) -> "LocalizationEvaluator":
        graph = ProjectGraph.load(graph_path)
        tasks = LocalizationTaskSet.model_validate_json(tasks_path.read_text(encoding="utf-8"))
        return cls(graph, tasks)

    def run(
        self,
        *,
        bootstrap_resamples: int = 10_000,
        bootstrap_seed: int = 42,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        max_k = max(self.task_set.ks)
        for task in self.task_set.tasks:
            for variant in ("A0", "A1", "A2"):
                result = self.retriever.retrieve(task.query, variant, limit=max(20, max_k))
                rows.append(self._score(task, result))
        aggregates = {
            variant: aggregate_variant(
                [row for row in rows if row["variant"] == variant],
                self.task_set.ks,
            )
            for variant in ("A0", "A1", "A2")
        }
        return {
            "schema_version": LOCALIZATION_RESULT_SCHEMA,
            "project_path": self.task_set.project_path,
            "task_count": len(self.task_set.tasks),
            "ks": self.task_set.ks,
            "variants": {
                "A0": "text_code_rag",
                "A1": "code_graph_calls",
                "A2": "unity_code_asset_graph",
            },
            "aggregate": aggregates,
            "inference": infer_localization_statistics(
                rows,
                resamples=bootstrap_resamples,
                seed=bootstrap_seed,
            ),
            "results": rows,
        }

    def _score(
        self,
        task: LocalizationTask,
        result: LocalizationResult,
    ) -> dict[str, Any]:
        file_rank = [_norm(item["path"]) for item in result.files]
        object_rank = [
            _norm(str(item.get("hierarchy_path") or item.get("name", "")))
            for item in result.game_objects
        ]
        asset_rank = [_norm(item["path"]) for item in result.assets]
        metrics: dict[str, float] = {}
        for k in self.task_set.ks:
            metrics[f"file_recall@{k}"] = recall_at_k(file_rank, task.gold_files, k)
            metrics[f"file_precision@{k}"] = precision_at_k(file_rank, task.gold_files, k)
            metrics[f"gameobject_recall@{k}"] = recall_at_k(
                object_rank, task.gold_game_objects, k, contains=True
            )
            metrics[f"asset_recall@{k}"] = recall_at_k(
                asset_rank, task.gold_assets, k
            )
        metrics["dependency_path_recall"] = dependency_path_recall(
            result.dependency_paths,
            task.gold_dependency_paths,
        )
        return {
            "task_id": task.id,
            "variant": result.variant,
            "metrics": metrics,
            "ranking": result.to_dict(),
        }


def _norm(value: str) -> str:
    return value.replace("\\", "/").casefold()


def _matches(candidate: str, gold: str, *, contains: bool) -> bool:
    candidate = _norm(candidate)
    gold = _norm(gold)
    return gold in candidate if contains else candidate == gold


def recall_at_k(
    ranking: list[str],
    gold: list[str],
    k: int,
    *,
    contains: bool = False,
) -> float:
    if not gold:
        return 1.0
    hits = sum(
        any(_matches(candidate, expected, contains=contains) for candidate in ranking[:k])
        for expected in gold
    )
    return hits / len(gold)


def precision_at_k(
    ranking: list[str],
    gold: list[str],
    k: int,
) -> float:
    if k <= 0:
        return 0.0
    top = ranking[:k]
    if not top:
        return 0.0
    hits = sum(any(_matches(candidate, expected, contains=False) for expected in gold) for candidate in top)
    return hits / len(top)


def dependency_path_recall(
    predicted: list[dict[str, Any]],
    gold: list[GoldDependencyPath],
) -> float:
    if not gold:
        return 1.0
    hits = 0
    for expected in gold:
        for candidate in predicted:
            names = [_norm(str(value)) for value in candidate.get("node_names", [])]
            kinds = [str(value) for value in candidate.get("edge_kinds", [])]
            source_ok = not expected.source_contains or any(
                _norm(expected.source_contains) in value for value in names
            )
            target_ok = not expected.target_contains or any(
                _norm(expected.target_contains) in value for value in names
            )
            kinds_ok = not expected.edge_kinds or is_subsequence(expected.edge_kinds, kinds)
            if source_ok and target_ok and kinds_ok:
                hits += 1
                break
    return hits / len(gold)


def is_subsequence(expected: list[str], actual: list[str]) -> bool:
    iterator = iter(actual)
    return all(any(value == target for value in iterator) for target in expected)


def aggregate_variant(
    rows: list[dict[str, Any]],
    ks: list[int],
) -> dict[str, Any]:
    keys = [
        *(f"file_recall@{k}" for k in ks),
        *(f"file_precision@{k}" for k in ks),
        *(f"gameobject_recall@{k}" for k in ks),
        *(f"asset_recall@{k}" for k in ks),
        "dependency_path_recall",
    ]
    return {
        "tasks": len(rows),
        **{
            key: (
                sum(float(row["metrics"][key]) for row in rows) / len(rows)
                if rows else 0.0
            )
            for key in keys
        },
    }


def save_evaluation(result: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
