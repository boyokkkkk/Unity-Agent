from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .roslyn import RoslynCodeParser
from .schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph
from .store import ProjectGraphStore
from .unity_export import UnityEditorExporter


class ProjectGraphBuilder:
    def __init__(
        self,
        *,
        project_path: Path,
        output_dir: Path,
        editor_path: Path | None = None,
    ):
        self.project_path = project_path.resolve()
        self.output_dir = output_dir.resolve()
        self.editor_path = editor_path.resolve() if editor_path else None

    def build(
        self,
        *,
        code_only: bool = False,
        keep_unity_workspace: bool = False,
        unity_timeout_seconds: int = 1200,
    ) -> tuple[ProjectGraph, dict[str, Any]]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        code_graph = RoslynCodeParser().parse(
            self.project_path,
            output_path=self.output_dir / "roslyn-code-graph.json",
        )
        stages: dict[str, Any] = {
            "roslyn": {
                "status": "passed",
                "stats": code_graph.stats(),
            }
        }
        graph = code_graph
        if not code_only:
            if self.editor_path is None:
                raise ValueError("editor_path is required unless code_only=True")
            unity_graph, unity_metadata = UnityEditorExporter(self.editor_path).export(
                self.project_path,
                artifact_dir=self.output_dir / "unity-export",
                timeout_seconds=unity_timeout_seconds,
                keep_workspace=keep_unity_workspace,
            )
            stages["unity_editor"] = {
                "status": "passed",
                "stats": unity_graph.stats(),
                **unity_metadata,
            }
            graph.merge(unity_graph)
            resolution = resolve_code_asset_links(graph)
            stages["merge"] = resolution
        graph.metadata.update(
            {
                "builder": "game-agent-project-graph",
                "source_project": str(self.project_path),
                "code_only": code_only,
            }
        )
        errors = graph.validate()
        if errors:
            raise ValueError("Invalid merged project graph: " + "; ".join(errors[:20]))
        graph_path = self.output_dir / "project-graph.json"
        sqlite_path = self.output_dir / "project-graph.sqlite3"
        graph.save(graph_path)
        ProjectGraphStore(sqlite_path).save(graph)
        report = {
            "schema_version": "game-agent-project-graph-build-v1",
            "status": "passed",
            "project_path": str(self.project_path),
            "duration_ms": round((time.monotonic() - started) * 1000),
            "stats": graph.stats(),
            "stages": stages,
            "artifacts": {
                "graph_json": str(graph_path),
                "graph_sqlite": str(sqlite_path),
            },
        }
        (self.output_dir / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return graph, report


def resolve_code_asset_links(graph: ProjectGraph) -> dict[str, Any]:
    type_nodes: dict[str, Node] = {}
    methods: dict[tuple[str, str], list[Node]] = {}
    fields: dict[tuple[str, str], Node] = {}
    for node in graph.nodes.values():
        if node.kind in {NodeKind.CLASS, NodeKind.MONO_BEHAVIOUR}:
            type_nodes[node.name] = node
            type_nodes.setdefault(node.name.rsplit(".", 1)[-1], node)
        elif node.kind == NodeKind.METHOD:
            declaring = str(node.attributes.get("declaring_type", ""))
            methods.setdefault((declaring, node.name), []).append(node)
            methods.setdefault((declaring.rsplit(".", 1)[-1], node.name), []).append(node)
        elif node.kind == NodeKind.FIELD:
            declaring = str(node.attributes.get("declaring_type", ""))
            fields[(declaring, node.name)] = node
            fields.setdefault((declaring.rsplit(".", 1)[-1], node.name), node)

    component_links = 0
    for node in graph.nodes.values():
        if node.kind != NodeKind.COMPONENT:
            continue
        type_name = str(node.attributes.get("type_name", ""))
        symbol = type_nodes.get(type_name) or type_nodes.get(type_name.rsplit(".", 1)[-1])
        if symbol is not None:
            node.attributes["code_symbol_id"] = symbol.id
            component_links += 1

    rewritten: list[Edge] = []
    resolved_fields = 0
    resolved_events = 0
    removed_placeholders: set[str] = set()
    for edge in graph.edges:
        if edge.kind == EdgeKind.SERIALIZED_REF:
            component = graph.nodes.get(edge.source)
            if component is not None:
                type_name = str(component.attributes.get("type_name", ""))
                property_name = str(edge.attributes.get("property_path", "")).split(".", 1)[0]
                property_name = property_name.replace("Array", "").strip()
                field = fields.get((type_name, property_name)) or fields.get(
                    (type_name.rsplit(".", 1)[-1], property_name)
                )
                if field is not None:
                    rewritten.append(
                        Edge(
                            source=field.id,
                            target=edge.target,
                            kind=edge.kind,
                            attributes={
                                **edge.attributes,
                                "source_component_id": component.id,
                                "resolved_field": True,
                            },
                        )
                    )
                    resolved_fields += 1
                    continue
        if edge.kind == EdgeKind.UNITY_EVENT_CALL:
            placeholder = graph.nodes.get(edge.target)
            if placeholder and placeholder.attributes.get("placeholder"):
                target_type = str(placeholder.attributes.get("target_type", ""))
                candidates = methods.get((target_type, placeholder.name)) or methods.get(
                    (target_type.rsplit(".", 1)[-1], placeholder.name)
                )
                if candidates:
                    for candidate in dict.fromkeys(item.id for item in candidates):
                        rewritten.append(
                            Edge(
                                source=edge.source,
                                target=candidate,
                                kind=edge.kind,
                                attributes={**edge.attributes, "resolved_method": True},
                            )
                        )
                    removed_placeholders.add(placeholder.id)
                    resolved_events += 1
                    continue
        rewritten.append(edge)

    graph.edges = []
    graph._edge_keys = set()
    for edge in rewritten:
        graph.add_edge(edge)
    referenced = {edge.source for edge in graph.edges} | {edge.target for edge in graph.edges}
    for node_id in removed_placeholders:
        if node_id not in referenced:
            graph.nodes.pop(node_id, None)
    return {
        "status": "passed",
        "component_code_links": component_links,
        "serialized_fields_resolved": resolved_fields,
        "unity_events_resolved": resolved_events,
        "unresolved_event_placeholders": sum(
            1 for node in graph.nodes.values() if node.attributes.get("placeholder")
        ),
    }
