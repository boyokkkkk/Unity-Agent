from __future__ import annotations

import importlib.resources
import json
import shutil
import time
from pathlib import Path
from typing import Any

from game_agent.validation import _run_process

from .schema import Edge, EdgeKind, Node, NodeKind, ProjectGraph


EDITOR_EXPORT_SCHEMA_VERSION = "game-agent-unity-editor-export-v1"
COPY_IGNORE_NAMES = {
    ".git",
    ".vs",
    "Library",
    "Logs",
    "Temp",
    "obj",
    "Build",
    "Builds",
    "UserSettings",
}


class UnityEditorExportError(RuntimeError):
    pass


def _ignore_copy(directory: str, names: list[str]) -> set[str]:
    del directory
    blocked = {name.casefold() for name in COPY_IGNORE_NAMES}
    return {name for name in names if name.casefold() in blocked}


class UnityEditorExporter:
    """Export Unity objects through Editor APIs from an isolated project copy."""

    def __init__(self, editor_path: Path):
        self.editor_path = editor_path.resolve()

    def export(
        self,
        project_path: Path,
        *,
        artifact_dir: Path,
        timeout_seconds: int = 1200,
        keep_workspace: bool = False,
    ) -> tuple[ProjectGraph, dict[str, Any]]:
        project_path = project_path.resolve()
        artifact_dir = artifact_dir.resolve()
        workspace = artifact_dir / "unity-export-workspace"
        output = artifact_dir / "unity-editor-export.json"
        log = artifact_dir / "unity-editor-export.log"
        if not self.editor_path.is_file():
            raise FileNotFoundError(f"Unity Editor not found: {self.editor_path}")
        if not (project_path / "ProjectSettings" / "ProjectVersion.txt").is_file():
            raise FileNotFoundError(f"Invalid Unity project: {project_path}")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        if workspace.exists():
            shutil.rmtree(workspace)
        started = time.monotonic()
        shutil.copytree(project_path, workspace, ignore=_ignore_copy)
        editor_dir = workspace / "Assets" / "Editor"
        editor_dir.mkdir(parents=True, exist_ok=True)
        exporter_source = (
            importlib.resources.files("game_agent.project_graph")
            / "editor"
            / "ProjectGraphExporter.cs"
        )
        exporter_target = editor_dir / "GameAgentProjectGraphExporter.cs"
        exporter_target.write_text(exporter_source.read_text(encoding="utf-8"), encoding="utf-8")
        command = [
            str(self.editor_path),
            "-batchmode",
            "-quit",
            "-projectPath",
            str(workspace),
            "-executeMethod",
            "GameAgentProjectGraphExporter.Export",
            "-gameAgentGraphOutput",
            str(output),
            "-logFile",
            str(log),
        ]
        try:
            completed = _run_process(command, timeout_seconds)
            if completed.returncode != 0 or not output.is_file():
                tail = ""
                if log.is_file():
                    tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-100:])
                raise UnityEditorExportError(
                    f"Unity Editor export failed ({completed.returncode}); output={output.is_file()}\n{tail}"
                )
            data = json.loads(output.read_text(encoding="utf-8"))
            graph = unity_export_to_graph(data, project_path=project_path)
            metadata = {
                "command": command,
                "returncode": completed.returncode,
                "pid": int(getattr(completed, "pid", 0)),
                "duration_ms": round((time.monotonic() - started) * 1000),
                "workspace_isolated": True,
                "workspace_kept": keep_workspace,
                "log": str(log),
                "raw_export": str(output),
            }
            return graph, metadata
        finally:
            if not keep_workspace and workspace.exists():
                shutil.rmtree(workspace)


def unity_export_to_graph(
    data: dict[str, Any],
    *,
    project_path: Path | None = None,
) -> ProjectGraph:
    if data.get("schema_version") != EDITOR_EXPORT_SCHEMA_VERSION:
        raise ValueError(f"Unsupported Unity Editor export schema: {data.get('schema_version')}")
    graph = ProjectGraph(
        project_path=str(project_path or ""),
        metadata={
            "unity_exporter": "editor_api",
            "unity_version": data.get("unity_version", ""),
        },
    )
    asset_ids: set[str] = set()
    for raw in data.get("assets", []):
        kind = NodeKind(raw.get("kind", "ASSET"))
        node = Node(
            id=raw["id"],
            kind=kind,
            name=raw.get("name", ""),
            path=raw.get("path", ""),
            attributes={"guid": raw.get("guid", "")},
        )
        graph.add_node(node)
        asset_ids.add(node.id)
    for raw in data.get("game_objects", []):
        graph.add_node(
            Node(
                id=raw["id"],
                kind=NodeKind.GAME_OBJECT,
                name=raw.get("name", ""),
                path=raw.get("asset_path", ""),
                attributes={
                    "asset_id": raw.get("asset_id", ""),
                    "hierarchy_path": raw.get("hierarchy_path", ""),
                    "parent_id": raw.get("parent_id", ""),
                    "active": bool(raw.get("active", False)),
                    "tag": raw.get("tag", ""),
                    "layer": int(raw.get("layer", 0)),
                },
            )
        )
    for raw in data.get("components", []):
        graph.add_node(
            Node(
                id=raw["id"],
                kind=NodeKind.COMPONENT,
                name=raw.get("name", ""),
                path=raw.get("asset_path", ""),
                attributes={
                    "game_object_id": raw.get("game_object_id", ""),
                    "type_name": raw.get("type_name", ""),
                    "assembly_name": raw.get("assembly_name", ""),
                    "script_path": raw.get("script_path", ""),
                    "script_guid": raw.get("script_guid", ""),
                    "enabled": bool(raw.get("enabled", True)),
                },
            )
        )
    for raw in data.get("game_objects", []):
        owner = raw.get("parent_id") or raw.get("asset_id")
        graph.add_edge(
            Edge(
                source=owner,
                target=raw["id"],
                kind=EdgeKind.CONTAINS,
                attributes={
                    "hierarchy_path": raw.get("hierarchy_path", ""),
                    "direct": True,
                },
            )
        )
    for raw in data.get("components", []):
        graph.add_edge(
            Edge(
                source=raw["id"],
                target=raw.get("game_object_id", ""),
                kind=EdgeKind.ATTACHED_TO,
                attributes={"type_name": raw.get("type_name", "")},
            )
        )
    for raw in data.get("prefab_sources", []):
        graph.add_edge(
            Edge(
                source=raw["game_object_id"],
                target=raw["prefab_id"],
                kind=EdgeKind.PREFAB_SOURCE,
                attributes={"prefab_path": raw.get("prefab_path", "")},
            )
        )
    for raw in data.get("serialized_refs", []):
        graph.add_edge(
            Edge(
                source=raw["source_component_id"],
                target=raw["target_id"],
                kind=EdgeKind.SERIALIZED_REF,
                attributes={
                    "source_type": raw.get("source_type", ""),
                    "property_path": raw.get("property_path", ""),
                    "target_kind": raw.get("target_kind", ""),
                    "target_path": raw.get("target_path", ""),
                },
            )
        )
    # Target method IDs are resolved against Roslyn symbols during graph merge.
    for raw in data.get("unity_event_calls", []):
        placeholder = (
            f"unity-event-target:{raw.get('target_type', '')}:"
            f"{raw.get('method_name', '')}:{raw.get('target_id', '')}"
        )
        graph.add_node(
            Node(
                id=placeholder,
                kind=NodeKind.METHOD,
                name=raw.get("method_name", ""),
                attributes={
                    "target_type": raw.get("target_type", ""),
                    "target_object_id": raw.get("target_id", ""),
                    "placeholder": True,
                },
            )
        )
        graph.add_edge(
            Edge(
                source=raw["source_component_id"],
                target=placeholder,
                kind=EdgeKind.UNITY_EVENT_CALL,
                attributes={
                    "event_field": raw.get("event_field", ""),
                    "listener_index": int(raw.get("listener_index", 0)),
                },
            )
        )
    return graph
