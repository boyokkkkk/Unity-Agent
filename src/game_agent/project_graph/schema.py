from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


GRAPH_SCHEMA_VERSION = "game-agent-unity-project-graph-v1"


class NodeKind(str, Enum):
    CSHARP_FILE = "CSHARP_FILE"
    CLASS = "CLASS"
    METHOD = "METHOD"
    FIELD = "FIELD"
    MONO_BEHAVIOUR = "MONO_BEHAVIOUR"
    SCENE = "SCENE"
    PREFAB = "PREFAB"
    GAME_OBJECT = "GAME_OBJECT"
    COMPONENT = "COMPONENT"
    ASSET = "ASSET"


class EdgeKind(str, Enum):
    CALLS = "CALLS"
    SUBSCRIBES_TO = "SUBSCRIBES_TO"
    PUBLISHES_EVENT = "PUBLISHES_EVENT"
    WRITES_STATE = "WRITES_STATE"
    ATTACHED_TO = "ATTACHED_TO"
    CONTAINS = "CONTAINS"
    PREFAB_SOURCE = "PREFAB_SOURCE"
    SERIALIZED_REF = "SERIALIZED_REF"
    UNITY_EVENT_CALL = "UNITY_EVENT_CALL"


CORE_EDGE_KINDS = {
    EdgeKind.CALLS,
    EdgeKind.ATTACHED_TO,
    EdgeKind.CONTAINS,
    EdgeKind.PREFAB_SOURCE,
    EdgeKind.SERIALIZED_REF,
    EdgeKind.UNITY_EVENT_CALL,
}

CAUSAL_EDGE_KINDS = {
    EdgeKind.SUBSCRIBES_TO,
    EdgeKind.PUBLISHES_EVENT,
    EdgeKind.WRITES_STATE,
}


def stable_id(namespace: str, *parts: str) -> str:
    normalized = "\x1f".join(str(part).replace("\\", "/") for part in parts)
    digest = hashlib.sha256(f"{namespace}\x1e{normalized}".encode("utf-8")).hexdigest()[:20]
    return f"{namespace}:{digest}"


@dataclass(slots=True)
class Node:
    id: str
    kind: NodeKind
    name: str
    path: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Node":
        return cls(
            id=str(data["id"]),
            kind=NodeKind(data["kind"]),
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            attributes=dict(data.get("attributes", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "name": self.name,
            "path": self.path,
            "attributes": self.attributes,
        }


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    kind: EdgeKind
    attributes: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Edge":
        return cls(
            source=str(data["source"]),
            target=str(data["target"]),
            kind=EdgeKind(data["kind"]),
            attributes=dict(data.get("attributes", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind.value,
            "attributes": self.attributes,
        }


class ProjectGraph:
    def __init__(
        self,
        *,
        project_path: str = "",
        metadata: dict[str, Any] | None = None,
    ):
        self.project_path = project_path
        self.metadata = dict(metadata or {})
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, str, str]] = set()

    def add_node(self, node: Node) -> None:
        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return
        if existing.kind != node.kind:
            raise ValueError(f"Node kind conflict for {node.id}: {existing.kind} != {node.kind}")
        if not existing.path and node.path:
            existing.path = node.path
        existing.attributes.update(node.attributes)

    def add_edge(self, edge: Edge, *, require_nodes: bool = True) -> bool:
        if require_nodes and (edge.source not in self.nodes or edge.target not in self.nodes):
            return False
        attrs = json.dumps(edge.attributes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        key = (edge.source, edge.target, edge.kind.value, attrs)
        if key in self._edge_keys:
            return False
        self._edge_keys.add(key)
        self.edges.append(edge)
        return True

    def merge(self, other: "ProjectGraph") -> None:
        for node in other.nodes.values():
            self.add_node(node)
        for edge in other.edges:
            self.add_edge(edge)
        self.metadata.update(other.metadata)

    def iter_nodes(self, kinds: Iterable[NodeKind] | None = None) -> Iterable[Node]:
        allowed = set(kinds) if kinds is not None else None
        return (
            node for node in self.nodes.values()
            if allowed is None or node.kind in allowed
        )

    def validate(self, *, require_six_edge_kinds: bool = False) -> list[str]:
        errors: list[str] = []
        for edge in self.edges:
            if edge.source not in self.nodes:
                errors.append(f"missing source node: {edge.source}")
            if edge.target not in self.nodes:
                errors.append(f"missing target node: {edge.target}")
        if require_six_edge_kinds:
            present = {edge.kind for edge in self.edges}
            for kind in CORE_EDGE_KINDS:
                if kind not in present:
                    errors.append(f"missing edge kind: {kind.value}")
        return errors

    def stats(self) -> dict[str, Any]:
        node_counts = {kind.value: 0 for kind in NodeKind}
        edge_counts = {kind.value: 0 for kind in EdgeKind}
        for node in self.nodes.values():
            node_counts[node.kind.value] += 1
        for edge in self.edges:
            edge_counts[edge.kind.value] += 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "node_kinds": node_counts,
            "edge_kinds": edge_counts,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "project_path": self.project_path,
            "metadata": self.metadata,
            "stats": self.stats(),
            "nodes": [
                node.to_dict()
                for node in sorted(self.nodes.values(), key=lambda item: item.id)
            ],
            "edges": [
                edge.to_dict()
                for edge in sorted(
                    self.edges,
                    key=lambda item: (
                        item.kind.value,
                        item.source,
                        item.target,
                        json.dumps(item.attributes, sort_keys=True),
                    ),
                )
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProjectGraph":
        if data.get("schema_version") != GRAPH_SCHEMA_VERSION:
            raise ValueError(f"Unsupported project graph schema: {data.get('schema_version')}")
        graph = cls(
            project_path=str(data.get("project_path", "")),
            metadata=dict(data.get("metadata", {})),
        )
        for raw in data.get("nodes", []):
            graph.add_node(Node.from_dict(raw))
        for raw in data.get("edges", []):
            graph.add_edge(Edge.from_dict(raw))
        return graph

    @classmethod
    def load(cls, path: Path) -> "ProjectGraph":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)
