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
        "unity_asset_read",
        "Read and verify one indexed scene, prefab, or asset before a typed mutation.",
        {
            "node_id": {"type": "string"},
            "asset_path": {"type": "string"},
        },
    ),
    _tool(
        "code_file_read",
        "Read a bounded project-relative C# file and return its SHA-256 for deterministic patching.",
        {
            "node_id": {"type": "string"},
            "path": {"type": "string"},
            "start_line": {"type": "integer", "minimum": 1, "default": 1},
            "end_line": {"type": "integer", "minimum": 1},
            "max_chars": {"type": "integer", "minimum": 256, "maximum": 50000, "default": 12000},
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


_EVIDENCE_NODE_IDS = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 1,
    "description": "Project-graph node IDs that localize the target and were read before mutation.",
}
_ASSET_PATH = {
    "type": "string",
    "description": "Project-relative Assets/... scene or prefab path.",
}


TYPED_MUTATION_TOOLS = [
    _tool(
        "unity_gameobject_create",
        "Create a GameObject in an indexed scene or prefab. The controller checkpoints and saves the asset.",
        {
            "asset_path": _ASSET_PATH,
            "name": {"type": "string"},
            "parent_hierarchy_path": {"type": "string"},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "name", "evidence_node_ids"],
    ),
    _tool(
        "unity_gameobject_delete",
        "Delete a previously read GameObject from a scene or prefab.",
        {
            "asset_path": _ASSET_PATH,
            "hierarchy_path": {"type": "string"},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "hierarchy_path", "evidence_node_ids"],
    ),
    _tool(
        "unity_gameobject_rename",
        "Rename a previously read GameObject in a scene or prefab.",
        {
            "asset_path": _ASSET_PATH,
            "hierarchy_path": {"type": "string"},
            "new_name": {"type": "string"},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "hierarchy_path", "new_name", "evidence_node_ids"],
    ),
    _tool(
        "unity_component_add",
        "Add a Component by assembly-qualified or full type name to a previously read GameObject.",
        {
            "asset_path": _ASSET_PATH,
            "hierarchy_path": {"type": "string"},
            "component_type": {"type": "string"},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "hierarchy_path", "component_type", "evidence_node_ids"],
    ),
    _tool(
        "unity_component_remove",
        "Remove one previously read Component from a GameObject.",
        {
            "asset_path": _ASSET_PATH,
            "hierarchy_path": {"type": "string"},
            "component_type": {"type": "string"},
            "component_index": {"type": "integer", "minimum": 0, "default": 0},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "hierarchy_path", "component_type", "evidence_node_ids"],
    ),
    _tool(
        "unity_serialized_property_set",
        "Set a SerializedProperty on a previously read Component using a JSON value.",
        {
            "asset_path": _ASSET_PATH,
            "hierarchy_path": {"type": "string"},
            "component_type": {"type": "string"},
            "component_index": {"type": "integer", "minimum": 0, "default": 0},
            "property_path": {"type": "string"},
            "value_json": {
                "type": "string",
                "description": "JSON-encoded value. Object references use an Assets/... path string.",
            },
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        [
            "asset_path", "hierarchy_path", "component_type", "property_path",
            "value_json", "evidence_node_ids",
        ],
    ),
    _tool(
        "unity_prefab_create",
        "Create or replace a prefab from a previously read GameObject in a scene or prefab.",
        {
            "source_asset_path": _ASSET_PATH,
            "source_hierarchy_path": {"type": "string"},
            "prefab_path": {
                "type": "string",
                "description": "Destination project-relative Assets/...prefab path.",
            },
            "replace_existing": {"type": "boolean", "default": False},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["source_asset_path", "source_hierarchy_path", "prefab_path", "evidence_node_ids"],
    ),
    _tool(
        "unity_asset_save",
        "Explicitly save an indexed scene or prefab after a typed edit.",
        {
            "asset_path": _ASSET_PATH,
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "evidence_node_ids"],
    ),
    _tool(
        "unity_asset_import",
        "Import or refresh a previously localized Unity asset through AssetDatabase.",
        {
            "asset_path": {
                "type": "string",
                "description": "Project-relative Assets/... path to import.",
            },
            "force_update": {"type": "boolean", "default": True},
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["asset_path", "evidence_node_ids"],
    ),
    _tool(
        "unity_script_patch",
        "Apply one deterministic exact-text replacement to a previously read C# file.",
        {
            "path": {"type": "string", "description": "Project-relative Assets/...cs path."},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "expected_sha256": {
                "type": "string",
                "description": "SHA-256 of the file content that was read before patching.",
            },
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
        },
        ["path", "old_text", "new_text", "expected_sha256", "evidence_node_ids"],
    ),
    _tool(
        "unity_execute_csharp",
        "Escape hatch for Unity Editor C# when no typed mutation covers the operation. Usage is measured.",
        {
            "code": {"type": "string"},
            "target_paths": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Every asset or source path the code may modify; all are checkpointed.",
            },
            "evidence_node_ids": _EVIDENCE_NODE_IDS,
            "request_editor_status": {
                "type": "string",
                "enum": ["editing"],
                "default": "editing",
            },
        },
        ["code", "target_paths", "evidence_node_ids", "request_editor_status"],
    ),
]


CONTROL_TOOLS = [
    _tool(
        "unity_recompile",
        "Run a Unity batchmode compile and record compiler verification for the pending change.",
        {},
    ),
    _tool(
        "unity_hot_reload",
        "Attempt method hot reload. This runtime reports unavailable until a live Editor bridge is connected.",
        {
            "paths": {"type": "array", "items": {"type": "string"}},
        },
    ),
    _tool(
        "unity_validate",
        "Run required Unity EditMode and/or PlayMode validation for the pending checkpoint.",
        {
            "modes": {
                "type": "array",
                "items": {"type": "string", "enum": ["editmode", "playmode"]},
                "minItems": 1,
            },
        },
        ["modes"],
    ),
]


MUTATION_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in TYPED_MUTATION_TOOLS)
CONTROL_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in CONTROL_TOOLS)
ACI_TOOLS = [*STRUCTURED_QUERY_TOOLS, *TYPED_MUTATION_TOOLS, *CONTROL_TOOLS]
ACI_TOOL_NAMES = QUERY_TOOL_NAMES | MUTATION_TOOL_NAMES | CONTROL_TOOL_NAMES

LOCALIZATION_TOOL_NAMES = frozenset(
    {
        "code_symbol_search",
        "unity_asset_search",
        "code_find_references",
        "code_file_read",
        "artifact_read",
    }
)
IMPLEMENTATION_READ_TOOL_NAMES = frozenset(
    {
        "unity_object_read",
        "unity_asset_read",
        "code_file_read",
        "code_find_references",
        "code_diagnostics",
        "artifact_read",
    }
)
ASSET_MUTATION_TOOL_NAMES = frozenset(
    MUTATION_TOOL_NAMES - {"unity_script_patch", "unity_execute_csharp"}
)
SCRIPT_MUTATION_TOOL_NAMES = frozenset({"unity_script_patch"})
VALIDATION_TOOL_NAMES = frozenset(
    {
        "code_diagnostics",
        "unity_recompile",
        "unity_hot_reload",
        "unity_validate",
        "artifact_read",
    }
)
