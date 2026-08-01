from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from game_agent.project_graph.schema import NodeKind

from .candidate import CandidateFrontier, CandidateRef


@dataclass(frozen=True, slots=True)
class GraphEntityRef:
    node_id: str
    entity_type: str
    path: str
    symbol: str
    repository_revision: str


class GraphResolver:
    """Resolve public candidate aliases and paths into canonical graph entities."""

    def __init__(self, context: Any, frontier: CandidateFrontier) -> None:
        self.context = context
        self.frontier = frontier

    def candidate(self, candidate_id: str) -> GraphEntityRef:
        candidate = self.frontier.get(candidate_id)
        if candidate is None:
            raise ValueError(f"Unknown candidate_id: {candidate_id}")
        return self._ref(candidate)

    def resolve_path(self, path: str, *, symbol: str = "") -> GraphEntityRef:
        normalized = path.replace("\\", "/")
        matches = [
            node for node in self._nodes()
            if node.path.replace("\\", "/").casefold() == normalized.casefold()
            and (not symbol or node.name.casefold() == symbol.casefold())
        ]
        if not matches:
            raise ValueError(f"No project-graph entity matches {normalized}")
        if symbol:
            exact = matches
        else:
            exact = [node for node in matches if node.kind == NodeKind.CSHARP_FILE] or matches
        exact.sort(key=lambda node: (node.kind.value, node.name.casefold(), node.id))
        node = exact[0]
        return GraphEntityRef(
            node_id=node.id,
            entity_type=node.kind.value,
            path=node.path.replace("\\", "/"),
            symbol=node.name if node.kind not in {NodeKind.CSHARP_FILE, NodeKind.SCENE, NodeKind.PREFAB, NodeKind.ASSET} else "",
            repository_revision=self._revision(),
        )

    def candidate_read_action(self, arguments: dict[str, Any]) -> tuple[dict[str, Any], GraphEntityRef]:
        candidate_id = str(arguments.get("candidate_id", "")).upper()
        ref = self.candidate(candidate_id)
        view = str(arguments.get("view", "preview"))
        if ref.path.casefold().endswith(".cs"):
            query: dict[str, Any] = {
                "node_id": ref.node_id,
                "path": ref.path,
                "max_chars": 50000 if view == "full" else 12000,
            }
            node = self._node(ref.node_id)
            line = int(node.attributes.get("line", 0) or 0) if node is not None else 0
            end_line = int(node.attributes.get("end_line", 0) or 0) if node is not None else 0
            if view == "preview" and line:
                query["start_line"] = max(1, line - 30)
                query["end_line"] = max(line, min(end_line or line + 60, line + 60))
            elif view == "symbol" and line:
                query["start_line"] = line
                query["end_line"] = max(line, end_line or line + 200)
            return {"tool": "code_file_read", "arguments": query}, ref
        return {
            "tool": "unity_asset_read",
            "arguments": {"node_id": ref.node_id, "asset_path": ref.path},
        }, ref

    def _ref(self, candidate: CandidateRef) -> GraphEntityRef:
        node = self._node(candidate.node_id)
        if node is None:
            raise ValueError(f"Candidate {candidate.candidate_id} is stale or missing from the graph")
        if node.path.replace("\\", "/").casefold() != candidate.path.casefold():
            raise ValueError(f"Candidate {candidate.candidate_id} no longer resolves to its recorded path")
        return GraphEntityRef(
            node_id=node.id,
            entity_type=node.kind.value,
            path=node.path.replace("\\", "/"),
            symbol=candidate.symbol,
            repository_revision=self._revision(),
        )

    def _node(self, node_id: str) -> Any | None:
        store = self.context.project_store
        return store.graph.nodes.get(node_id) if store is not None else None

    def _nodes(self) -> list[Any]:
        store = self.context.project_store
        return list(store.graph.nodes.values()) if store is not None else []

    def _revision(self) -> str:
        store = self.context.project_store
        if store is None:
            return ""
        return str(store.graph.metadata.get("project_revision", "") or store.graph.metadata.get("revision", ""))
