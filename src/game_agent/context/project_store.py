from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from game_agent.project_graph.retrieval import LocalizationRetriever
from game_agent.project_graph.schema import GRAPH_SCHEMA_VERSION, Node, NodeKind, ProjectGraph

from .models import TaskWorkingSet, WorkingSetEntry


@dataclass(slots=True)
class GraphVersion:
    project_id: str
    project_path: str
    schema_version: str
    graph_digest: str
    project_revision: str
    loaded_at: float
    generation: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectContextStore:
    """Versioned project knowledge shared by task-local working sets."""

    _graph_cache: dict[tuple[str, str], ProjectGraph] = {}

    def __init__(
        self,
        graph: ProjectGraph,
        *,
        project_root: Path,
        graph_digest: str,
        state_path: Path | None = None,
    ) -> None:
        self.graph = graph
        self.project_root = project_root.resolve()
        self.state_path = state_path.resolve() if state_path else None
        normalized = self.project_root.as_posix().casefold()
        project_id = "project:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        revision = str(
            graph.metadata.get("project_revision")
            or graph.metadata.get("git_commit")
            or graph.metadata.get("tree_hash")
            or graph_digest[:16]
        )
        self.version = GraphVersion(
            project_id=project_id,
            project_path=self.project_root.as_posix(),
            schema_version=GRAPH_SCHEMA_VERSION,
            graph_digest=graph_digest,
            project_revision=revision,
            loaded_at=time.time(),
        )
        self.working_sets: dict[str, TaskWorkingSet] = {}
        self.dirty_nodes: dict[str, str] = {}
        self.invalidations: list[dict[str, Any]] = []
        self._path_index: dict[str, list[str]] = {}
        self._path_sources: dict[str, str] = {}
        self._signatures: dict[tuple[str, str, str], str] = {}
        self._file_stats: dict[str, tuple[int, int] | None] = {}
        self._build_indexes()
        self._snapshot_files()
        self._retriever = LocalizationRetriever(self.graph, self.project_root)
        self.retrieval_treatment_metrics: dict[str, int] = {}
        self.last_retrieval_treatment: dict[str, Any] = {}

    @classmethod
    def open(
        cls,
        graph_path: Path,
        *,
        project_root: Path,
        state_path: Path | None = None,
    ) -> "ProjectContextStore":
        resolved = graph_path.resolve()
        raw = resolved.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        key = (str(resolved), digest)
        graph = cls._graph_cache.get(key)
        if graph is None:
            graph = ProjectGraph.from_dict(json.loads(raw.decode("utf-8")))
            cls._graph_cache[key] = graph
        return cls(graph, project_root=project_root, graph_digest=digest, state_path=state_path)

    @classmethod
    def from_graph(
        cls,
        graph: ProjectGraph,
        *,
        project_root: Path,
        state_path: Path | None = None,
    ) -> "ProjectContextStore":
        payload = json.dumps(graph.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return cls(
            graph,
            project_root=project_root,
            graph_digest=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            state_path=state_path,
        )

    def working_set(self, task_id: str, *, max_entries: int = 24) -> TaskWorkingSet:
        if task_id not in self.working_sets:
            self.working_sets[task_id] = TaskWorkingSet(task_id, max_entries=max_entries)
        working_set = self.working_sets[task_id]
        if max_entries < working_set.max_entries:
            working_set.max_entries = max_entries
            working_set._bound_entries()
        return working_set

    def locate(
        self,
        task_id: str,
        query: str,
        *,
        limit: int = 12,
        strategy: str = "role_mmr",
        max_test_candidates: int = 1,
        mmr_lambda: float = 0.82,
        semantic_model: str = "",
        semantic_weight: float = 0.35,
        semantic_cache_path: Path | None = None,
        causal_query_decomposition: bool = False,
        causal_role_retention: bool = False,
        graph_retrieval_enabled: bool = True,
        causal_edges_enabled: bool = True,
    ) -> list[WorkingSetEntry]:
        causal_task = is_causal_query(query)
        queries = _decompose_causal_query(query) if causal_query_decomposition and causal_task else [query]
        results = [
            self._retriever.retrieve(
                subquery,
                "A2",
                limit=max(limit * 3, 12) if len(queries) > 1 else limit,
                strategy=strategy,
                max_test_candidates=max_test_candidates,
                mmr_lambda=mmr_lambda,
                semantic_model=semantic_model,
                semantic_weight=semantic_weight,
                semantic_cache_path=semantic_cache_path,
                graph_retrieval_enabled=graph_retrieval_enabled,
                causal_edges_enabled=causal_edges_enabled,
            )
            for subquery in queries
        ]
        for result in results:
            self.last_retrieval_treatment = dict(result.treatment)
            for key, value in result.treatment.items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    self.retrieval_treatment_metrics[key] = (
                        self.retrieval_treatment_metrics.get(key, 0) + value
                    )
        # Localization is consumed as a bounded *file* frontier.  Previously
        # ranked symbol IDs were sliced before paths were merged and before
        # file scores could affect ordering.  Aggregate every source by path,
        # retain one useful symbol representative, then rank and truncate the
        # merged groups.  Non-code graph objects remain independent groups.
        ranked_by_path: dict[str, list[str]] = {}
        for result in results:
            for item in result.ranked_nodes:
                node_id = str(item["id"])
                node = self.graph.nodes.get(node_id)
                if node is not None and node.path:
                    ranked_by_path.setdefault(_normalize_path(node.path), []).append(node_id)

        groups: dict[str, dict[str, Any]] = {}
        insertion = 0

        def add(node_id: str, score: float, *, path: str = "", rrf: float = 0.0) -> None:
            nonlocal insertion
            node = self.graph.nodes[node_id]
            path_key = _normalize_path(path or node.path)
            key = f"path:{path_key}" if path_key else f"node:{node_id}"
            existing = groups.get(key)
            if existing is None:
                groups[key] = {
                    "node_id": node_id, "score": score, "rrf": rrf, "order": insertion
                }
                insertion += 1
                return
            existing["score"] = max(float(existing["score"]), score)
            existing["rrf"] = float(existing.get("rrf", 0.0)) + rrf

        for result in results:
            for rank, item in enumerate(result.files, start=1):
                path = str(item.get("path", ""))
                path_key = _normalize_path(path)
                path_nodes = self._path_index.get(path_key, [])
                representative = next(
                    (node_id for node_id in ranked_by_path.get(path_key, []) if node_id in path_nodes),
                    next(
                        (
                            node_id for node_id in path_nodes
                            if self.graph.nodes[node_id].kind == NodeKind.CSHARP_FILE
                        ),
                        path_nodes[0] if path_nodes else "",
                    ),
                )
                if representative:
                    add(
                        representative,
                        float(item.get("score", 0.0)),
                        path=path,
                        rrf=1.0 / (60.0 + rank),
                    )

        for result in results:
            for collection in (result.ranked_nodes, result.game_objects, result.assets):
                for item in collection:
                    node_id = str(item["id"])
                    node = self.graph.nodes.get(node_id)
                    if node is not None:
                        add(node_id, float(item.get("score", 0.0)), path=node.path)
        if len(results) > 1:
            sort_key = lambda item: (
                    -float(item.get("rrf", 0.0)),
                    -float(item["score"]),
                    int(item["order"]),
                )
        else:
            sort_key = lambda item: (-float(item["score"]), int(item["order"]))
        ordered = sorted(groups.values(), key=sort_key)
        if len(results) > 1:
            maximum_rrf = max((float(item.get("rrf", 0.0)) for item in ordered), default=1.0)
            for item in ordered:
                item["score"] = float(item.get("rrf", 0.0)) / max(maximum_rrf, 1e-12)
        if causal_role_retention and causal_task:
            ordered = _retain_causal_roles(ordered, self.graph, limit, query=query)
        else:
            ordered = ordered[:limit]
        working_set = self.working_set(task_id)
        entries = []
        for item in ordered:
            node_id = str(item["node_id"])
            score = float(item["score"])
            node = self.graph.nodes[node_id]
            entry = working_set.add(self._entry(node, relevance=score))
            entries.append(entry)
        self.save_state()
        return entries

    def map_paths(self, task_id: str, paths: Iterable[str]) -> list[WorkingSetEntry]:
        working_set = self.working_set(task_id)
        results: list[WorkingSetEntry] = []
        for path in paths:
            for node_id in self._path_index.get(_normalize_path(path), []):
                results.append(working_set.add(self._entry(self.graph.nodes[node_id], relevance=1.0)))
        return results

    def map_node_ids(
        self,
        task_id: str,
        node_ids: Iterable[str],
        *,
        relevance: float = 1.0,
    ) -> list[WorkingSetEntry]:
        """Map known graph nodes into a task working set without retrieval side effects."""
        working_set = self.working_set(task_id)
        results: list[WorkingSetEntry] = []
        for node_id in dict.fromkeys(str(value) for value in node_ids if value):
            node = self.graph.nodes.get(node_id)
            if node is not None:
                results.append(working_set.add(self._entry(node, relevance=relevance)))
        if results:
            self.save_state()
        return results

    def materialize(self, task_id: str, node_id: str) -> dict[str, Any] | None:
        working_set = self.working_set(task_id)
        entry = working_set.entries.get(node_id)
        if entry is None:
            working_set.context_misses += 1
            return None
        if node_id in self.dirty_nodes:
            working_set.record_access(node_id, hit=False)
            entry.status = "stale"
            entry.stale_reason = self.dirty_nodes[node_id]
            entry.detail = None
            return None
        hit = entry.detail is not None
        working_set.record_access(node_id, hit=hit)
        if entry.detail is None:
            node = self.graph.nodes.get(node_id)
            if node is None:
                return None
            entry.detail = self._node_detail(node)
            entry.status = "mapped"
        return entry.detail

    def detect_changes(self) -> list[str]:
        changed: list[str] = []
        for path, previous in list(self._file_stats.items()):
            current = self._stat(self._path_sources.get(path, path))
            if current != previous:
                changed.append(path)
                self._file_stats[path] = current
        if changed:
            self.invalidate_paths(changed, reason="project_file_changed")
        return changed

    def invalidate_paths(self, paths: Iterable[str], *, reason: str) -> set[str]:
        normalized_paths = {_normalize_path(path) for path in paths if path}
        affected = {
            node_id
            for path in normalized_paths
            for node_id in self._path_index.get(path, [])
        }
        frontier = set(affected)
        for edge in self.graph.edges:
            if edge.source in frontier or edge.target in frontier:
                affected.update({edge.source, edge.target})
        if not affected:
            return set()
        for node_id in affected:
            self.dirty_nodes[node_id] = reason
        for working_set in self.working_sets.values():
            working_set.mark_stale(affected, reason)
        self.version.generation += 1
        self.invalidations.append(
            {
                "generation": self.version.generation,
                "paths": sorted(normalized_paths),
                "node_ids": sorted(affected),
                "reason": reason,
                "timestamp": time.time(),
            }
        )
        self.save_state()
        return affected

    def refresh(self, graph: ProjectGraph, *, graph_digest: str = "") -> dict[str, int]:
        old_sets = list(self.working_sets.values())
        self.graph = graph
        self.version.graph_digest = graph_digest or hashlib.sha256(
            json.dumps(graph.to_dict(), sort_keys=True).encode("utf-8")
        ).hexdigest()
        self.version.project_revision = str(
            graph.metadata.get("project_revision")
            or graph.metadata.get("git_commit")
            or self.version.graph_digest[:16]
        )
        self.version.generation += 1
        self.version.loaded_at = time.time()
        self.dirty_nodes.clear()
        self._build_indexes()
        self._retriever = LocalizationRetriever(self.graph, self.project_root)
        remapped = 0
        missing = 0
        for working_set in old_sets:
            for old_id, entry in list(working_set.entries.items()):
                target_id = old_id if old_id in graph.nodes else self._signatures.get(
                    (entry.kind, _normalize_path(entry.path), entry.name.casefold())
                )
                if target_id is None:
                    entry.status = "stale"
                    entry.stale_reason = "node_missing_after_refresh"
                    entry.detail = None
                    missing += 1
                    continue
                if target_id != old_id:
                    working_set.entries.pop(old_id)
                    entry.node_id = target_id
                    working_set.entries[target_id] = entry
                node = graph.nodes[target_id]
                entry.kind = node.kind.value
                entry.name = node.name
                entry.path = node.path
                entry.detail = None
                entry.status = "remapped"
                entry.stale_reason = ""
                working_set.remaps += 1
                remapped += 1
        self._snapshot_files()
        self.save_state()
        return {"remapped": remapped, "missing": missing}

    def save_state(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        temporary = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def metrics(self) -> dict[str, Any]:
        aggregate_hits = sum(item.context_hits for item in self.working_sets.values())
        aggregate_misses = sum(item.context_misses for item in self.working_sets.values())
        total = aggregate_hits + aggregate_misses
        return {
            "context_hits": aggregate_hits,
            "context_misses": aggregate_misses,
            "context_hit_rate": aggregate_hits / total if total else 0.0,
            "context_miss_rate": aggregate_misses / total if total else 0.0,
            "dirty_nodes": len(self.dirty_nodes),
            "invalidations": len(self.invalidations),
            "tasks": len(self.working_sets),
            "retrieval_treatment": dict(self.retrieval_treatment_metrics),
            "last_retrieval_treatment": dict(self.last_retrieval_treatment),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version.to_dict(),
            "metrics": self.metrics(),
            "dirty_nodes": self.dirty_nodes,
            "invalidations": self.invalidations,
            "working_sets": {key: value.to_dict() for key, value in self.working_sets.items()},
        }

    def _build_indexes(self) -> None:
        self._path_index = {}
        self._path_sources = {}
        self._signatures = {}
        for node in self.graph.nodes.values():
            paths = {node.path, str(node.attributes.get("script_path", ""))}
            for path in paths:
                if path:
                    normalized = _normalize_path(path)
                    self._path_index.setdefault(normalized, []).append(node.id)
                    self._path_sources.setdefault(normalized, path.replace("\\", "/"))
            self._signatures[(node.kind.value, _normalize_path(node.path), node.name.casefold())] = node.id

    def _snapshot_files(self) -> None:
        self._file_stats = {
            path: self._stat(self._path_sources.get(path, path))
            for path in self._path_index
        }

    def _stat(self, relative: str) -> tuple[int, int] | None:
        target = self.project_root / relative
        try:
            stat = target.stat()
        except OSError:
            return None
        return stat.st_mtime_ns, stat.st_size

    def _entry(self, node: Node, *, relevance: float) -> WorkingSetEntry:
        return WorkingSetEntry(
            node_id=node.id,
            kind=node.kind.value,
            name=node.name,
            path=node.path,
            relevance=relevance,
        )

    def _node_detail(self, node: Node) -> dict[str, Any]:
        detail = {
            "id": node.id,
            "kind": node.kind.value,
            "name": node.name,
            "path": node.path,
            "attributes": node.attributes,
        }
        line = int(node.attributes.get("line", 0) or 0)
        if line > 0 and node.path.casefold().endswith(".cs"):
            target = self.project_root / node.path
            if target.is_file():
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
                start = max(1, line - 5)
                end = min(len(lines), line + 7)
                detail["source_range"] = {"start_line": start, "end_line": end}
                detail["source_excerpt"] = [
                    {"line": index, "text": lines[index - 1]}
                    for index in range(start, end + 1)
                ]
        return detail


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./").casefold()


def _decompose_causal_query(query: str) -> list[str]:
    """Split a causal report while retaining its task-specific domain anchors."""
    if not is_causal_query(query):
        return [query]
    anchors = _query_domain_anchors(query)
    anchor_text = " ".join(anchors)
    parts = [
        query,
        f"{anchor_text} trigger input action event source publisher",
        f"{anchor_text} state transition manager controller",
        f"{anchor_text} event publication invoke publisher",
        f"{anchor_text} UI popup observer subscriber handler refresh",
    ]
    return list(dict.fromkeys(part.strip() for part in parts if part.strip()))


_QUERY_STOPWORDS = {
    "after", "appears", "broken", "does", "failure", "game", "locate", "make",
    "neither", "other", "player", "presses", "repair", "screen", "smallest",
    "the", "then", "while", "with", "work", "works", "validate", "root", "cause",
    "event", "chain", "state", "changes", "refresh", "update", "missing", "behavior",
}


def _query_domain_anchors(query: str) -> list[str]:
    """Return stable identifiers/nouns that distinguish this causal subsystem."""
    anchors: list[str] = []
    for token in _search_tokens(query):
        if len(token) < 4 or token in _QUERY_STOPWORDS:
            continue
        if token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 5:
            token = token[:-1]
        if token not in anchors:
            anchors.append(token)
    return anchors[:12]


def _search_tokens(text: str) -> list[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    return [
        match.group(0).casefold()
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]", expanded)
    ]


def is_causal_query(query: str) -> bool:
    """Return whether a task describes a cross-component causal notification chain.

    Generic words such as ``UI``, ``input``, and ``state`` are deliberately
    insufficient: treating every UI defect as an event-chain task caused causal
    role quotas to evict the actual OptionUI candidate.
    """
    lowered = query.casefold()
    explicit = (
        "event", "subscriber", "subscription", "publish", "observer", "notification",
        "事件", "订阅", "发布", "观察者", "通知",
    )
    if any(marker in lowered for marker in explicit):
        return True
    transition = any(marker in lowered for marker in (
        "state", "transition", "countdown", "状态", "切换", "倒计时",
    ))
    observer_symptom = any(marker in lowered for marker in (
        "ui", "refresh", "notify", "tutorial", "界面", "刷新", "通知", "教程",
    ))
    return transition and observer_symptom


def _causal_role(node: Node) -> str:
    value = f"{node.name} {Path(node.path).stem} {node.kind.value}".casefold()
    if "test" in value:
        return "test"
    if any(token in value for token in ("manager", "controller", "state", "coordinator")):
        return "controller"
    if any(token in value for token in ("input", "interaction", "event", "counter")):
        return "event_source"
    if any(token in value for token in ("ui", "view", "panel", "canvas")):
        return "ui"
    return "source"


def _retain_causal_roles(
    ordered: list[dict[str, Any]], graph: ProjectGraph, limit: int, *, query: str = ""
) -> list[dict[str, Any]]:
    """Reserve causal roles only from candidates tied to the task's domain."""
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    anchors = set(_query_domain_anchors(query))

    def domain_overlap(item: dict[str, Any]) -> bool:
        if not anchors:
            return True
        node = graph.nodes[str(item["node_id"])]
        node_text = " ".join((node.name, node.path, *(str(value) for value in node.attributes.values())))
        return bool(anchors.intersection(_search_tokens(node_text)))

    for role in ("event_source", "controller", "ui"):
        match = next(
            (
                item for item in ordered
                if str(item["node_id"]) not in selected_ids
                and domain_overlap(item)
                and _causal_role(graph.nodes[str(item["node_id"])]) == role
            ),
            None,
        )
        if match is not None:
            selected.append(match)
            selected_ids.add(str(match["node_id"]))
    selected.extend(
        item for item in ordered if str(item["node_id"]) not in selected_ids
    )
    return selected[:limit]
