from __future__ import annotations

import hashlib
import json
import os
import re
from collections import deque
from pathlib import Path
from typing import Any, TYPE_CHECKING

from game_agent.project_graph.retrieval import tokenize
from game_agent.project_graph.schema import EdgeKind, Node, NodeKind
from game_agent.validation import find_unity_editor

from .schemas import QUERY_TOOL_NAMES

if TYPE_CHECKING:
    from game_agent.context import ContextAssembler, ProjectContextStore


ASSET_KINDS = {NodeKind.SCENE, NodeKind.PREFAB, NodeKind.ASSET, NodeKind.CSHARP_FILE}
CODE_KINDS = {NodeKind.CSHARP_FILE, NodeKind.CLASS, NodeKind.MONO_BEHAVIOUR, NodeKind.METHOD, NodeKind.FIELD}
OBJECT_KINDS = {NodeKind.GAME_OBJECT, NodeKind.COMPONENT}


class StructuredQueryExecutor:
    """Bounded read-only Unity queries backed by the P1 project context."""

    def __init__(self, context: "ContextAssembler", *, project_root: Path, artifact_root: Path | None = None) -> None:
        self.context = context
        self.project_root = project_root.resolve()
        self.artifact_root = artifact_root.resolve() if artifact_root else None

    @property
    def store(self) -> "ProjectContextStore | None":
        return self.context.project_store

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = str(action.get("tool", ""))
        args = action.get("arguments", {})
        if tool not in QUERY_TOOL_NAMES:
            return self._error(tool, "unknown_query", f"Unknown query tool: {tool}")
        if not isinstance(args, dict):
            return self._error(tool, "invalid_arguments", "Arguments must be an object.")
        try:
            return getattr(self, f"_{tool}")(args)
        except (TypeError, ValueError) as exc:
            return self._error(tool, "invalid_arguments", str(exc))
        except OSError as exc:
            return self._error(tool, "query_io_error", str(exc))

    def _unity_editor_status(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        version_file = self.project_root / "ProjectSettings" / "ProjectVersion.txt"
        version = ""
        if version_file.is_file():
            match = re.search(r"m_EditorVersion:\s*([^\s]+)", version_file.read_text(encoding="utf-8", errors="replace"))
            version = match.group(1) if match else ""
        editor = find_unity_editor(self.project_root)
        instance_file = self.project_root / "Library" / "EditorInstance.json"
        instance: dict[str, Any] = {}
        if instance_file.is_file():
            try:
                instance = json.loads(instance_file.read_text(encoding="utf-8", errors="replace"))
            except (json.JSONDecodeError, OSError):
                pass
        pid = int(instance.get("process_id") or instance.get("processId") or 0)
        return self._ok("unity_editor_status", {
            "status": "available", "editor_state": "disconnected", "bridge_connected": False,
            "project_valid": version_file.is_file(), "unity_version": version,
            "editor_path": str(editor) if editor else "", "editor_process_detected": _process_exists(pid),
            "editor_process_id": pid or None,
            "capabilities": {"live_editor_state": False, "offline_project_queries": self.store is not None},
            "reason": "No Unity Editor bridge is implemented; live editing/playing state cannot be asserted.",
        }, status="observed", claim="Observed offline Unity project and Editor availability.")

    def _unity_asset_search(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_asset_search")
        if unavailable:
            return unavailable
        query = _required(args, "query")
        kinds = _node_kinds(args.get("kinds"), ASSET_KINDS)
        nodes = self._search(query, kinds, str(args.get("path_prefix", "")), _limit(args))
        return self._nodes("unity_asset_search", query, nodes)

    def _unity_ref_search(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_ref_search")
        if unavailable:
            return unavailable
        seeds = self._resolve(node_id=str(args.get("node_id", "")), path=str(args.get("asset_path", "")))
        if not seeds:
            return self._empty("unity_ref_search", "No matching seed node.")
        direction = str(args.get("direction", "references"))
        if direction not in {"references", "dependencies"}:
            raise ValueError("direction must be references or dependencies")
        rows, found = self._walk(
            [node.id for node in seeds], incoming=direction == "references",
            depth=max(1, min(6, int(args.get("max_depth", 1)))), edges=_edge_kinds(args.get("edge_kinds")),
            kinds=_node_kinds(args.get("node_kinds"), None), limit=_limit(args),
        )
        ids = [node.id for node in seeds] + found
        self._map(ids)
        return self._ok("unity_ref_search", {
            "status": "ok", "direction": direction, "seeds": [_summary(node) for node in seeds],
            "total": len(rows), "results": rows,
        }, ids=ids, sources=_graph_sources(ids), status="observed",
            claim=f"Observed {len(rows)} indexed {direction} relation(s).")

    def _unity_object_list(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_object_list")
        if unavailable:
            return unavailable
        path = _required(args, "asset_path")
        prefix = str(args.get("hierarchy_prefix", "")).strip("/").casefold()
        kinds = OBJECT_KINDS if bool(args.get("include_components", True)) else {NodeKind.GAME_OBJECT}
        nodes = [node for node in self.store.graph.nodes.values() if node.kind in kinds and _same(node.path, path)]
        if prefix:
            nodes = [node for node in nodes if self._hierarchy(node).casefold().startswith(prefix)]
        nodes.sort(key=lambda node: (self._hierarchy(node).casefold(), node.kind.value, node.name.casefold()))
        return self._nodes("unity_object_list", path, nodes[:_limit(args)])

    def _unity_object_search(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_object_search")
        if unavailable:
            return unavailable
        query = _required(args, "query")
        kinds = OBJECT_KINDS if bool(args.get("include_components", True)) else {NodeKind.GAME_OBJECT}
        nodes = self._search(query, kinds, str(args.get("asset_path", "")), _limit(args))
        return self._nodes("unity_object_search", query, nodes)

    def _unity_object_read(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_object_read")
        if unavailable:
            return unavailable
        nodes = self._resolve(
            node_id=str(args.get("node_id", "")), path=str(args.get("asset_path", "")),
            hierarchy=str(args.get("hierarchy_path", "")), kinds=OBJECT_KINDS,
        )
        if not nodes:
            return self._empty("unity_object_read", "No matching GameObject or Component.")
        target = nodes[0]
        source = (self.project_root / target.path).resolve()
        if source != self.project_root and self.project_root not in source.parents:
            return self._error("unity_object_read", "project_scope", "indexed object path escapes the Unity project")
        if not source.is_file():
            return self._error(
                "unity_object_read",
                "asset_missing",
                f"Indexed Unity object asset does not exist: {target.path}",
            )
        if target.id in self.store.dirty_nodes:
            return self._error(
                "unity_object_read",
                "stale_graph_node",
                f"Indexed Unity object is stale and must be rebuilt before mutation: {target.id}",
            )
        ids = [target.id]
        components: list[dict[str, Any]] = []
        if bool(args.get("include_components", True)):
            component_ids = self._component_ids(target)
            ids.extend(component_ids)
            components = [value for value in (self._materialize(node_id) for node_id in component_ids) if value]
        relations: list[dict[str, Any]] = []
        if bool(args.get("include_references", True)):
            anchor_ids = set(ids)
            for edge in self.store.graph.edges:
                outgoing = edge.source in anchor_ids
                incoming = edge.target in anchor_ids
                if not outgoing and not incoming:
                    continue
                other = self.store.graph.nodes.get(edge.target if outgoing else edge.source)
                if other:
                    ids.append(other.id)
                    relations.append({"direction": "outgoing" if outgoing else "incoming", "edge_kind": edge.kind.value, "attributes": edge.attributes, "node": _summary(other)})
        self._map(ids)
        return self._ok("unity_object_read", {
            "status": "ok", "object": self._materialize(target.id), "components": components, "relations": relations,
        }, ids=ids, sources=_graph_sources(ids), status="source_verified",
            claim=f"Read indexed Unity object detail for {target.name} ({target.path}).")

    def _code_symbol_search(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("code_symbol_search")
        if unavailable:
            return unavailable
        query = _required(args, "query")
        kinds = (_node_kinds(args.get("kinds"), CODE_KINDS) or set()) & CODE_KINDS
        return self._nodes("code_symbol_search", query, self._search(query, kinds, str(args.get("path_prefix", "")), _limit(args)))

    def _code_find_references(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("code_find_references")
        if unavailable:
            return unavailable
        seeds = self._resolve(node_id=str(args.get("node_id", "")), path=str(args.get("file_path", "")), name=str(args.get("symbol", "")), kinds=CODE_KINDS)
        if not seeds:
            return self._empty("code_find_references", "No matching code symbol.")
        direction = str(args.get("direction", "incoming"))
        if direction not in {"incoming", "outgoing", "both"}:
            raise ValueError("direction must be incoming, outgoing, or both")
        seed_ids = {node.id for node in seeds}
        allowed = _edge_kinds(args.get("edge_kinds"))
        rows, ids = [], [node.id for node in seeds]
        for edge in self.store.graph.edges:
            match = (direction in {"incoming", "both"} and edge.target in seed_ids) or (direction in {"outgoing", "both"} and edge.source in seed_ids)
            if not match or (allowed and edge.kind not in allowed):
                continue
            source, target = self.store.graph.nodes.get(edge.source), self.store.graph.nodes.get(edge.target)
            if source and target:
                ids.extend([source.id, target.id])
                rows.append({"edge_kind": edge.kind.value, "source": _summary(source), "target": _summary(target), "attributes": edge.attributes})
            if len(rows) >= _limit(args):
                break
        self._map(ids)
        return self._ok("code_find_references", {
            "status": "ok", "direction": direction, "seeds": [_summary(node) for node in seeds], "total": len(rows), "results": rows,
        }, ids=ids, sources=_graph_sources(ids), status="observed", claim=f"Observed {len(rows)} indexed reference edge(s) for {seeds[0].name}.")

    def _unity_asset_read(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("unity_asset_read")
        if unavailable:
            return unavailable
        nodes = self._resolve(
            node_id=str(args.get("node_id", "")),
            path=str(args.get("asset_path", "")),
            kinds=ASSET_KINDS,
        )
        if not nodes:
            return self._empty("unity_asset_read", "No matching indexed Unity asset.")
        node = nodes[0]
        target = (self.project_root / node.path).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            return self._error("unity_asset_read", "project_scope", "indexed asset path escapes the Unity project")
        if not target.is_file():
            return self._error(
                "unity_asset_read",
                "asset_missing",
                f"Indexed Unity asset does not exist: {node.path}",
            )
        if node.id in self.store.dirty_nodes:
            return self._error(
                "unity_asset_read",
                "stale_graph_node",
                f"Indexed Unity asset is stale and must be rebuilt before mutation: {node.id}",
            )
        detail = self._materialize(node.id) or _summary(node)
        return self._ok(
            "unity_asset_read",
            {"status": "ok", "asset": detail},
            ids=[node.id],
            sources=[f"graph:{node.id}", node.path],
            status="source_verified",
            claim=f"Read indexed Unity asset {node.name} ({node.path}).",
        )

    def _code_file_read(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("code_file_read")
        if unavailable:
            return unavailable
        nodes = self._resolve(
            node_id=str(args.get("node_id", "")),
            path=str(args.get("path", "")),
            kinds=CODE_KINDS,
        )
        if not nodes:
            return self._empty("code_file_read", "No matching indexed C# file or symbol.")
        node = nodes[0]
        relative = node.path
        target = (self.project_root / relative).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            return self._error("code_file_read", "project_scope", "path escapes the Unity project")
        if not target.is_file():
            return self._error("code_file_read", "source_missing", f"Source does not exist: {relative}")
        raw = target.read_bytes()
        sha256 = hashlib.sha256(raw).hexdigest()
        lines = raw.decode("utf-8", errors="replace").splitlines()
        start = max(1, int(args.get("start_line", 1)))
        end = min(len(lines), int(args.get("end_line", start + 199)))
        if end < start:
            raise ValueError("end_line must be >= start_line")
        maximum = max(256, min(50000, int(args.get("max_chars", 12000))))
        content = "\n".join(lines[start - 1:end])

        # Persist full file content to evidence artifact for mutation execution
        from game_agent.context import EvidenceLedger
        evidence_id = EvidenceLedger.id_for(
            f"Read source file {relative} at SHA-256 {sha256}.",
            [f"source:{relative}:{start}-{end}"]
        )
        artifact_relative = ""
        if self.artifact_root:
            artifact_dir = self.artifact_root / "evidence-artifacts"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact_file = artifact_dir / f"{evidence_id.replace(':', '_')}.txt"
            # Store full file content, not just the viewed range
            full_content = "\n".join(lines)
            artifact_file.write_text(full_content, encoding="utf-8")
            artifact_relative = artifact_file.relative_to(self.artifact_root).as_posix()

        self._map([node.id])
        payload = {
            "status": "ok",
            "node": _summary(node),
            "path": relative,
            "sha256": sha256,
            "start_line": start,
            "end_line": end,
            "total_lines": len(lines),
            "truncated": len(content) > maximum,
            "content": content[:maximum],
            "evidence_artifact": artifact_relative,
        }
        return self._ok(
            "code_file_read",
            payload,
            ids=[node.id],
            sources=[f"source:{relative}:{start}-{end}"],
            status="source_verified",
            claim=f"Read source file {relative} at SHA-256 {sha256}.",
            artifact_path=artifact_relative,
            artifact_sha256=sha256,
        )

    def _code_diagnostics(self, args: dict[str, Any]) -> dict[str, Any]:
        unavailable = self._need_graph("code_diagnostics")
        if unavailable:
            return unavailable
        path = str(args.get("file_path", "")).strip()
        diagnostics = [{"severity": "error", "source": "project_graph", "message": value} for value in self.store.graph.validate()]
        for node in self.store.graph.nodes.values():
            if node.kind not in CODE_KINDS or (path and not _same(node.path, path)):
                continue
            if node.path and not (self.project_root / node.path).is_file():
                diagnostics.append({"severity": "warning", "source": "project_graph", "node_id": node.id, "path": node.path, "message": "Indexed source file is missing."})
            if node.attributes.get("placeholder"):
                diagnostics.append({"severity": "warning", "source": "project_graph", "node_id": node.id, "path": node.path, "message": "UnityEvent target was not resolved to a Roslyn symbol."})
        stored = self.store.graph.metadata.get("diagnostics", [])
        if isinstance(stored, list):
            diagnostics.extend(item for item in stored if isinstance(item, dict))
        rank, minimum = {"info": 0, "warning": 1, "error": 2}, str(args.get("min_severity", "warning"))
        diagnostics = [item for item in diagnostics if rank.get(str(item.get("severity", "warning")), 1) >= rank.get(minimum, 1)]
        diagnostics = diagnostics[:max(1, min(400, int(args.get("max_results", 100))))]
        ids = [str(item["node_id"]) for item in diagnostics if item.get("node_id")]
        self._map(ids)
        return self._ok("code_diagnostics", {
            "status": "partial", "scope": str(args.get("scope", "file" if path else "workspace")),
            "file_path": path, "provider": "project_graph", "compiler_diagnostics_available": False,
            "compile_verified": False, "total": len(diagnostics), "diagnostics": diagnostics,
            "limitation": "No live Roslyn workspace server is connected; run compile validation for compiler verification.",
        }, ids=ids, sources=_graph_sources(ids), status="observed",
            claim=f"Observed {len(diagnostics)} graph diagnostic(s); compilation was not verified.")

    def _artifact_read(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.artifact_root is None:
            return self._unavailable("artifact_read", "No artifact store is configured.")
        reference = _required(args, "artifact_ref")
        value = Path(reference)
        target = value.resolve() if value.is_absolute() else (self.artifact_root / value).resolve()
        if target != self.artifact_root and self.artifact_root not in target.parents:
            return self._error("artifact_read", "artifact_scope", "artifact_ref escapes the artifact store")
        if not target.is_file():
            return self._error("artifact_read", "artifact_missing", f"Artifact does not exist: {reference}")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(args.get("start_line", 1)))
        end = min(len(lines), int(args.get("end_line", start + 199)))
        if end < start:
            raise ValueError("end_line must be >= start_line")
        maximum = max(256, min(50000, int(args.get("max_chars", 12000))))
        content = "\n".join(lines[start - 1:end])
        payload = {"status": "ok", "artifact_ref": reference, "start_line": start, "end_line": end, "total_lines": len(lines), "truncated": len(content) > maximum, "content": content[:maximum]}
        source = f"artifact:{reference}:{start}-{end}"
        return self._ok("artifact_read", payload, sources=[source], status="source_verified", claim=f"Read {source}.")

    def _need_graph(self, tool: str) -> dict[str, Any] | None:
        return None if self.store is not None else self._unavailable(tool, "No project graph is configured; set context.graph_path.")

    def _search(
        self,
        query: str,
        kinds: set[NodeKind],
        prefix: str,
        limit: int,
    ) -> list[tuple[float, Node]]:
        terms, path_prefix = tokenize(query), _norm(prefix)
        scored: list[tuple[int, Node]] = []
        for node in self.store.graph.nodes.values():
            if node.kind not in kinds or (path_prefix and not _norm(node.path).startswith(path_prefix)):
                continue
            text = " ".join([node.name, node.path, *map(str, node.attributes.values())])
            tokens, lower = tokenize(text), text.casefold()
            score = sum(tokens.count(term) + (2 if term in lower else 0) for term in terms)
            if score:
                scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].path.casefold(), item[1].name.casefold(), item[1].id))
        return [(float(score), node) for score, node in scored[:limit]]

    def _resolve(self, *, node_id: str = "", path: str = "", hierarchy: str = "", name: str = "", kinds: set[NodeKind] | None = None) -> list[Node]:
        if node_id:
            node = self.store.graph.nodes.get(node_id)
            return [node] if node and (kinds is None or node.kind in kinds) else []
        return [node for node in self.store.graph.nodes.values() if (kinds is None or node.kind in kinds) and (not path or _same(node.path, path)) and (not hierarchy or str(node.attributes.get("hierarchy_path", "")).casefold() == hierarchy.casefold()) and (not name or name.casefold() in node.name.casefold()) and (path or hierarchy or name)]

    def _walk(self, seeds: list[str], *, incoming: bool, depth: int, edges: set[EdgeKind], kinds: set[NodeKind] | None, limit: int) -> tuple[list[dict[str, Any]], list[str]]:
        queue, visited, rows, ids = deque((node_id, 0) for node_id in seeds), set(seeds), [], []
        while queue and len(rows) < limit:
            current, level = queue.popleft()
            if level >= depth:
                continue
            for edge in self.store.graph.edges:
                if (edge.target if incoming else edge.source) != current or (edges and edge.kind not in edges):
                    continue
                next_id = edge.source if incoming else edge.target
                node = self.store.graph.nodes.get(next_id)
                if not node:
                    continue
                if kinds is None or node.kind in kinds:
                    rows.append({"depth": level + 1, "edge_kind": edge.kind.value, "attributes": edge.attributes, "node": _summary(node)})
                    ids.append(node.id)
                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, level + 1))
                if len(rows) >= limit:
                    break
        return rows, ids

    def _hierarchy(self, node: Node) -> str:
        if node.kind == NodeKind.GAME_OBJECT:
            return str(node.attributes.get("hierarchy_path", ""))
        owner = self.store.graph.nodes.get(str(node.attributes.get("game_object_id", "")))
        return str(owner.attributes.get("hierarchy_path", "")) if owner else ""

    def _component_ids(self, node: Node) -> list[str]:
        if node.kind == NodeKind.COMPONENT:
            return [node.id]
        return [edge.source for edge in self.store.graph.edges if edge.kind == EdgeKind.ATTACHED_TO and edge.target == node.id]

    def _materialize(self, node_id: str) -> dict[str, Any] | None:
        self._map([node_id])
        return self.store.materialize(self.context.task_id or "unbound", node_id)

    def _map(self, ids: list[str]) -> None:
        if self.store:
            self.store.map_node_ids(self.context.task_id or "unbound", ids)

    def _nodes(
        self,
        tool: str,
        query: str,
        nodes: list[Node] | list[tuple[float, Node]],
    ) -> dict[str, Any]:
        ranked: list[tuple[float | None, Node]] = [
            (float(item[0]), item[1]) if isinstance(item, tuple) else (None, item)
            for item in nodes
        ]
        ids = [node.id for _, node in ranked]
        self._map(ids)
        results = []
        for score, node in ranked:
            summary = _summary(node)
            if score is not None:
                summary["score"] = score
            results.append(summary)
        return self._ok(tool, {"status": "ok", "query": query, "total": len(ranked), "results": results}, ids=ids, sources=_graph_sources(ids), status="observed", claim=f"Observed {len(ranked)} indexed candidate(s) for {query!r}.")

    def _ok(self, tool: str, payload: dict[str, Any], *, ids: list[str] | None = None, sources: list[str] | None = None, status: str = "", claim: str = "", artifact_path: str = "", artifact_sha256: str = "") -> dict[str, Any]:
        extra = {"aci": True, "query_tool": tool, "structured": payload, "node_ids": list(dict.fromkeys(ids or [])), "evidence_sources": list(dict.fromkeys(sources or [])), "evidence_status": status, "evidence_claim": claim}
        if artifact_path:
            extra["evidence_artifact_path"] = artifact_path
        if artifact_sha256:
            extra["evidence_artifact_sha256"] = artifact_sha256
        return {"output": json.dumps(payload, ensure_ascii=False, indent=2), "returncode": 0, "exception_info": "", "extra": extra}

    def _empty(self, tool: str, reason: str) -> dict[str, Any]:
        return self._ok(tool, {"status": "ok", "total": 0, "results": [], "reason": reason})

    def _unavailable(self, tool: str, reason: str) -> dict[str, Any]:
        return self._ok(tool, {"status": "unavailable", "reason": reason})

    @staticmethod
    def _error(tool: str, code: str, message: str) -> dict[str, Any]:
        payload = {"status": "error", "error_code": code, "message": message}
        return {"output": json.dumps(payload, ensure_ascii=False, indent=2), "returncode": -2, "exception_info": message, "extra": {"aci": True, "query_tool": tool, "structured": payload}}


def _required(args: dict[str, Any], key: str) -> str:
    value = str(args.get(key, "")).strip()
    if not value:
        raise ValueError(f"{key} must be non-empty")
    return value


def _limit(args: dict[str, Any]) -> int:
    return max(1, min(200, int(args.get("limit", 20))))


def _node_kinds(value: Any, default: set[NodeKind] | None) -> set[NodeKind] | None:
    if value in (None, []):
        return set(default) if default is not None else None
    if not isinstance(value, list):
        raise ValueError("kinds must be an array")
    return {NodeKind(str(item)) for item in value}


def _edge_kinds(value: Any) -> set[EdgeKind]:
    if value in (None, []):
        return set()
    if not isinstance(value, list):
        raise ValueError("edge_kinds must be an array")
    return {EdgeKind(str(item)) for item in value}


def _summary(node: Node) -> dict[str, Any]:
    return {"id": node.id, "kind": node.kind.value, "name": node.name, "path": node.path, "attributes": node.attributes}


def _graph_sources(ids: list[str]) -> list[str]:
    return [f"graph:{node_id}" for node_id in dict.fromkeys(ids)]


def _norm(value: str) -> str:
    return value.replace("\\", "/").lstrip("./").casefold()


def _same(left: str, right: str) -> bool:
    return _norm(left) == _norm(right)


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, PermissionError):
        return False
