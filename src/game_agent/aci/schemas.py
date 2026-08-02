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
        "candidate_read",
        "Read a Controller-selected project-graph candidate without copying an internal node_id.",
        {
            "candidate_id": {
                "type": "string",
                "description": "Public task-local candidate alias such as C1 or C2.",
                "pattern": "^C[1-9][0-9]*$",
            },
            "view": {
                "type": "string",
                "enum": ["preview", "symbol", "full"],
                "default": "preview",
            },
            "focus": {
                "type": "string",
                "description": "Optional semantic focus for the bounded read.",
            },
        },
        ["candidate_id"],
    ),
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


_DIAGNOSIS_PROPERTIES = {
    "symptom": {"type": "string", "minLength": 1},
    "root_targets": {
        "type": "array",
        "items": {"type": "string", "pattern": "^C[1-9][0-9]*$"},
        "minItems": 1,
    },
    "causal_chain": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "statement": {"type": "string", "minLength": 1},
                "subject": {"type": "string", "minLength": 1},
                "predicate": {
                    "type": "string",
                    "enum": [
                        "DECLARES_EVENT", "SUBSCRIBES_TO", "WRITES_STATE",
                        "PUBLISHES_EVENT", "OBSERVER_EFFECT",
                    ],
                },
                "object": {"type": "string", "minLength": 1},
                "polarity": {"type": "string", "enum": ["present", "absent", "unknown"]},
                "fact_ids": {
                    "type": "array", "items": {"type": "string", "pattern": "^fact:"}, "minItems": 1,
                },
                "negative_evidence": {
                    "type": "object",
                    "properties": {
                        "scope": {"type": "string", "minLength": 1},
                        "edge_kind": {"type": "string", "minLength": 1},
                        "graph_revision": {"type": "string", "minLength": 1},
                        "observed_matches": {"type": "integer", "minimum": 0},
                        "complete": {"type": "boolean"},
                    },
                    "required": ["scope", "edge_kind", "graph_revision", "observed_matches", "complete"],
                    "additionalProperties": False,
                },
                "evidence_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            },
            "required": ["subject", "predicate", "object", "polarity", "fact_ids"],
            "additionalProperties": False,
        },
        "minItems": 1,
    },
    "proposed_mutations": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "pattern": "^C[1-9][0-9]*$"},
                "operation": {"type": "string", "minLength": 1},
                "target_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional exact new/destination paths authorized by this mutation.",
                },
                "evidence_id": {
                    "type": "string",
                    "description": "For C# edits, the source-verified evidence ID that grounds the exact patch anchor.",
                },
                "old_text": {
                    "type": "string",
                    "description": "For C# edits, exact existing source text copied from the verified target; it must match exactly once.",
                },
                "new_text": {
                    "type": "string",
                    "description": "For C# edits, the exact replacement text authorized by this diagnosis.",
                },
            },
            "required": ["target", "operation"],
            "additionalProperties": False,
        },
        "minItems": 1,
    },
    "validation_plan": {
        "type": "array",
        "items": {"type": "string", "enum": ["compile", "editmode", "playmode"]},
        "minItems": 1,
    },
    "remaining_uncertainty": {"type": "array", "items": {"type": "string"}},
}

_PLAN_TOOL = _tool(
    "task_plan_submit",
    "Submit the task objective, evidence needs, success criteria, and required validation before exploration.",
    {
        "objective": {"type": "string", "minLength": 1},
        "hypotheses": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "required_evidence": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "success_criteria": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "validation_plan": {
            "type": "array",
            "items": {"type": "string", "enum": ["compile", "editmode", "playmode"]},
            "minItems": 1,
        },
    },
    ["objective", "hypotheses", "required_evidence", "success_criteria", "validation_plan"],
)

_DIAGNOSIS_TOOLS = [
    _tool(
        name,
        description,
        _DIAGNOSIS_PROPERTIES,
        [
            "symptom", "root_targets", "causal_chain",
            "validation_plan", "remaining_uncertainty",
        ],
    )
    for name, description in (
        ("diagnosis_submit", """Submit an evidence-linked root-cause diagnosis and request mutation authorization.

FIELDS:
- symptom: one-sentence user-facing problem description
- root_targets: array of candidate IDs (e.g., ["C5"]) where the fix will be applied
- causal_chain: choose structured atomic claims using subject, predicate, object, polarity, and fact_ids copied exactly from workflow.causal_fact_matrix. The controller derives statement, verified evidence_ids, and negative_evidence from the cited facts; do not copy those redundant fields.
- proposed_mutations (optional): legacy combined-mode field. Omit when the workflow exposes patch_prepare; the accepted diagnosis will advance to a separate AST patch stage.
- validation_plan: array from ["compile", "editmode", "playmode"]
- remaining_uncertainty: array of strings (use empty array [] if no uncertainty)"""),
        ("diagnosis_revise", """Create a new diagnosis version after a rejected or outdated diagnosis.

FIELDS:
- symptom: one-sentence user-facing problem description
- root_targets: array of candidate IDs (e.g., ["C5"]) where the fix will be applied
- causal_chain: choose structured atomic claims using subject, predicate, object, polarity, and fact_ids copied exactly from workflow.causal_fact_matrix. The controller derives statement, verified evidence_ids, and negative_evidence from the cited facts; do not copy those redundant fields.
- proposed_mutations (optional): legacy combined-mode field. Omit when the workflow exposes patch_prepare; the accepted diagnosis will advance to a separate AST patch stage.
- validation_plan: array from ["compile", "editmode", "playmode"]
- remaining_uncertainty: array of strings (use empty array [] if no uncertainty)"""),
    )
]
_PATCH_PREPARE_TOOL = _tool(
    "patch_prepare",
    "Prepare an evidence-authorized C# patch after diagnosis acceptance. Use a controller causal fact for event-publication insertion, or ast_replace_exact with one unique inspected source anchor for other repairs.",
    {
        "target": {"type": "string", "pattern": "^C[1-9][0-9]*$"},
        "causal_fact_id": {"type": "string", "pattern": "^fact:"},
        "operation": {"type": "string", "enum": ["ast_insert_after", "ast_insert_before", "ast_replace_exact"]},
        "evidence_id": {"type": "string", "minLength": 1},
        "use_repair_exemplar": {"type": "boolean", "default": True},
        "insertion_text": {
            "type": "string",
            "description": "Optional replacement for the fact's repair_exemplar. Prefer use_repair_exemplar=true when an exemplar exists.",
        },
        "anchor_text": {
            "type": "string",
            "description": "For ast_replace_exact, exact text observed in the diagnosed file; it must occur once.",
        },
        "replacement_text": {
            "type": "string",
            "description": "For ast_replace_exact, the complete replacement for anchor_text.",
        },
    },
    ["target", "operation", "evidence_id"],
)
_PATCH_APPLY_TOOL = _tool(
    "patch_apply",
    "Apply the exact controller-prepared mutation identified by patch_token. Do not copy old_text/new_text.",
    {
        "patch_token": {"type": "string", "pattern": "^patch:"},
    },
    ["patch_token"],
)
_REVIEW_TOOL = _tool(
    "workflow_review",
    "Run the controller-owned final review of actual diff scope, authorization, and validation results.",
    {},
)
WORKFLOW_TOOLS = [
    _PLAN_TOOL, *_DIAGNOSIS_TOOLS, _PATCH_PREPARE_TOOL, _PATCH_APPLY_TOOL, _REVIEW_TOOL,
]
WORKFLOW_TOOL_NAMES = frozenset(tool["function"]["name"] for tool in WORKFLOW_TOOLS)


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
            "evidence_id": {
                "type": "string",
                "description": "The evidence ID from code_file_read that diagnosed this change.",
            },
            "evidence_artifact_path": {
                "type": "string",
                "description": "Path to the evidence artifact containing the diagnosed file content.",
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

ACI_TOOLS = [*STRUCTURED_QUERY_TOOLS, *WORKFLOW_TOOLS, *TYPED_MUTATION_TOOLS, *CONTROL_TOOLS]
ACI_TOOL_NAMES = QUERY_TOOL_NAMES | WORKFLOW_TOOL_NAMES | MUTATION_TOOL_NAMES | CONTROL_TOOL_NAMES

LOCALIZATION_TOOL_NAMES = frozenset(
    {
        "code_symbol_search",
        "unity_asset_search",
        "code_find_references",
        "code_file_read",
        "artifact_read",
    }
)
CANDIDATE_TOOL_NAMES = frozenset({"candidate_read"})
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
