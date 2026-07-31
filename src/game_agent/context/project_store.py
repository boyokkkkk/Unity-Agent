from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from game_agent.project_graph.retrieval import LocalizationRetriever
from game_agent.project_graph.schema import GRAPH_SCHEMA_VERSION, Node, ProjectGraph

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

    def locate(self, task_id: str, query: str, *, limit: int = 12) -> list[WorkingSetEntry]:
        result = self._retriever.retrieve(query, "A2", limit=limit)
        scores: dict[str, float] = {}
        for item in result.ranked_nodes:
            scores[str(item["id"])] = max(scores.get(str(item["id"]), 0.0), float(item.get("score", 0.0)))
        for collection in (result.game_objects, result.assets):
            for item in collection:
                scores[str(item["id"])] = max(scores.get(str(item["id"]), 0.0), float(item.get("score", 0.0)))
        for item in result.files:
            for node_id in self._path_index.get(_normalize_path(str(item.get("path", ""))), []):
                scores[node_id] = max(scores.get(node_id, 0.0), float(item.get("score", 0.0)))
        working_set = self.working_set(task_id)
        entries = []
        for node_id, score in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]:
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
