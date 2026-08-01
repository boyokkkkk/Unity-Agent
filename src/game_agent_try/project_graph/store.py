from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

import networkx as nx

from .schema import EdgeKind, NodeKind, ProjectGraph


SQLITE_SCHEMA_VERSION = "game-agent-unity-project-graph-sqlite-v1"


class ProjectGraphStore:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def save(self, graph: ProjectGraph) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        if temporary.exists():
            temporary.unlink()
        connection = sqlite3.connect(temporary)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode = DELETE;
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );
                CREATE TABLE nodes (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE TABLE edges (
                    edge_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL REFERENCES nodes(id),
                    target TEXT NOT NULL REFERENCES nodes(id),
                    kind TEXT NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE INDEX idx_nodes_kind ON nodes(kind);
                CREATE INDEX idx_nodes_path ON nodes(path);
                CREATE INDEX idx_edges_source_kind ON edges(source, kind);
                CREATE INDEX idx_edges_target_kind ON edges(target, kind);
                """
            )
            metadata = {
                "schema_version": SQLITE_SCHEMA_VERSION,
                "project_path": graph.project_path,
                "graph_metadata": graph.metadata,
                "stats": graph.stats(),
            }
            connection.executemany(
                "INSERT INTO metadata(key, value_json) VALUES (?, ?)",
                [
                    (key, json.dumps(value, ensure_ascii=False, sort_keys=True))
                    for key, value in metadata.items()
                ],
            )
            connection.executemany(
                """
                INSERT INTO nodes(id, kind, name, path, attributes_json)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        node.id,
                        node.kind.value,
                        node.name,
                        node.path,
                        json.dumps(node.attributes, ensure_ascii=False, sort_keys=True),
                    )
                    for node in graph.nodes.values()
                ],
            )
            connection.executemany(
                """
                INSERT INTO edges(source, target, kind, attributes_json)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        edge.source,
                        edge.target,
                        edge.kind.value,
                        json.dumps(edge.attributes, ensure_ascii=False, sort_keys=True),
                    )
                    for edge in graph.edges
                ],
            )
            connection.commit()
        finally:
            connection.close()
        temporary.replace(self.path)

    def stats(self) -> dict[str, Any]:
        connection = sqlite3.connect(self.path)
        try:
            nodes = connection.execute(
                "SELECT kind, COUNT(*) FROM nodes GROUP BY kind ORDER BY kind"
            ).fetchall()
            edges = connection.execute(
                "SELECT kind, COUNT(*) FROM edges GROUP BY kind ORDER BY kind"
            ).fetchall()
        finally:
            connection.close()
        return {
            "nodes": {kind: count for kind, count in nodes},
            "edges": {kind: count for kind, count in edges},
        }

    def neighbors(
        self,
        node_id: str,
        *,
        edge_kinds: Iterable[EdgeKind] | None = None,
        direction: str = "both",
    ) -> list[dict[str, Any]]:
        if direction not in {"in", "out", "both"}:
            raise ValueError("direction must be in, out, or both")
        kinds = [kind.value for kind in edge_kinds or []]
        clauses: list[str] = []
        params: list[Any] = []
        if direction in {"out", "both"}:
            clauses.append("source = ?")
            params.append(node_id)
        if direction in {"in", "both"}:
            clauses.append("target = ?")
            params.append(node_id)
        query = "SELECT source, target, kind, attributes_json FROM edges WHERE (" + " OR ".join(clauses) + ")"
        if kinds:
            query += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
            params.extend(kinds)
        connection = sqlite3.connect(self.path)
        try:
            rows = connection.execute(query, params).fetchall()
        finally:
            connection.close()
        return [
            {
                "source": source,
                "target": target,
                "kind": kind,
                "attributes": json.loads(attributes),
            }
            for source, target, kind, attributes in rows
        ]


def to_networkx(
    graph: ProjectGraph,
    *,
    node_kinds: set[NodeKind] | None = None,
    edge_kinds: set[EdgeKind] | None = None,
) -> nx.MultiDiGraph:
    result = nx.MultiDiGraph(
        schema_version=SQLITE_SCHEMA_VERSION,
        project_path=graph.project_path,
    )
    for node in graph.nodes.values():
        if node_kinds is not None and node.kind not in node_kinds:
            continue
        result.add_node(
            node.id,
            kind=node.kind.value,
            name=node.name,
            path=node.path,
            **node.attributes,
        )
    for edge in graph.edges:
        if edge_kinds is not None and edge.kind not in edge_kinds:
            continue
        if edge.source not in result or edge.target not in result:
            continue
        result.add_edge(
            edge.source,
            edge.target,
            key=f"{edge.kind.value}:{result.number_of_edges(edge.source, edge.target)}",
            kind=edge.kind.value,
            **edge.attributes,
        )
    return result
