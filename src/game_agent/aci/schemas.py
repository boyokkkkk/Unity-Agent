from __future__ import annotations

from typing import Any


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
                "additionalProperties": False,
            },
        },
    }


_LIMIT = {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}
_NODE_KINDS = {
    "type": "array",
    "items": {
        "type": "string",
        "enum": [
            "CSHARP_FILE", "CLASS", "METHOD", "FIELD", "MONO_BEHAVIOUR",
            "SCENE", "PREFAB", "GAME_OBJECT", "COMPONENT", "ASSET",
        ],
    },
}
_EDGE_KINDS = {
    "type": "array",
    "items": {
        "type": "string",
        "enum": [
            "CALLS", "ATTACHED_TO", "CONTAINS", "PREFAB_SOURCE",
            "SERIALIZED_REF", "UNITY_EVENT_CALL",
        ],
    },
}


STRUCTURED_QUERY_TOOLS = [
    _tool(
        "unity_editor_status",
        "Inspect Unity project and Editor availability without changing Editor state. Reports bridge capability explicitly.",
        {},
    ),
    _tool(
        "unity_asset_search",
        "Search indexed Unity scenes, prefabs, assets, scripts, and related project-graph nodes. Results are mapped into the current task working set.",
        {
            "query": {"type": "string", "description": "Name, path, type, or semantic search terms."},
            "kinds": _NODE_KINDS,
            "path_prefix": {"type": "string", "description": "Optional project-relative path prefix."},
            "limit": _LIMIT,
        },
        ["query"],
    ),
    _tool(
        "unity_ref_search",
        "Traverse the indexed Unity/code reference graph in either direction from a node or asset path.",
        {
            "node_id": {"type": "string"},
            "asset_path": {"type": "string"},
            "direction": {"type": "string", "enum": ["references", "dependencies"], "default": "references"},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 6, "default": 1},
            "edge_kinds": _EDGE_KINDS,
            "node_kinds": _NODE_KINDS,
            "limit": _LIMIT,
        },
    ),
    _tool(
        "unity_object_list",
        "List indexed GameObjects and Components in a scene or prefab, optionally below a hierarchy prefix.",
        {
            "asset_path": {"type": "string", "description": "Scene or prefab path."},
            "hierarchy_prefix": {"type": "string"},
            "include_components": {"type": "boolean", "default": True},
            "limit": _LIMIT,
        },
        ["asset_path"],
    ),
    _tool(
        "unity_object_search",
        "Search indexed GameObjects and Components by name, hierarchy path, type, or asset path.",
        {
            "query": {"type": "string"},
            "asset_path": {"type": "string"},
            "include_components": {"type": "boolean", "default": True},
            "limit": _LIMIT,
        },
        ["query"],
    ),
    _tool(
        "unity_object_read",
        "Read precise indexed details for one GameObject or Component and its immediate relations.",
        {
            "node_id": {"type": "string"},
            "asset_path": {"type": "string"},
            "hierarchy_path": {"type": "string"},
            "include_components": {"type": "boolean", "default": True},
            "include_references": {"type": "boolean", "default": True},
        },
    ),
    _tool(
        "code_symbol_search",
        "Search indexed C# files, types, methods, and fields semantically without shell text parsing.",
        {
            "query": {"type": "string"},
            "kinds": _NODE_KINDS,
            "path_prefix": {"type": "string"},
            "limit": _LIMIT,
        },
        ["query"],
    ),
    _tool(
        "code_find_references",
        "Find indexed code calls, UnityEvent calls, serialized references, and code/asset relations for a symbol.",
        {
            "node_id": {"type": "string"},
            "symbol": {"type": "string", "description": "Symbol name used when node_id is unknown."},
            "file_path": {"type": "string"},
            "direction": {"type": "string", "enum": ["incoming", "outgoing", "both"], "default": "incoming"},
            "edge_kinds": _EDGE_KINDS,
            "limit": _LIMIT,
        },
    ),
    _tool(
        "code_diagnostics",
        "Read available C# and project-graph diagnostics. The response states whether compiler-grade diagnostics are available; it never treats graph checks as a successful compile.",
        {
            "file_path": {"type": "string"},
            "scope": {"type": "string", "enum": ["file", "workspace"], "default": "workspace"},
            "min_severity": {"type": "string", "enum": ["error", "warning", "info"], "default": "warning"},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 400, "default": 100},
        },
    ),
    _tool(
        "artifact_read",
        "Read a bounded line range from a tool-output artifact under the current run artifact store.",
        {
            "artifact_ref": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 1},
            "max_chars": {"type": "integer", "minimum": 256, "maximum": 50000, "default": 12000},
        },
        ["artifact_ref"],
    ),
]

QUERY_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in STRUCTURED_QUERY_TOOLS)
