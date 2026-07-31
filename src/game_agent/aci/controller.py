from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from game_agent.context import ContextAssembler, EvidenceStatus

from .mutation import AciConfig, UnityMutationExecutor
from .query import StructuredQueryExecutor
from .schemas import CONTROL_TOOL_NAMES, MUTATION_TOOL_NAMES, QUERY_TOOL_NAMES


@dataclass
class PendingChange:
    transaction_id: str
    tool: str
    checkpoint_id: str
    changed_paths: list[str]
    script_change: bool
    diagnostics_complete: bool = False
    reload_complete: bool = False
    validation_complete: bool = False
    required_validation_modes: list[str] = field(default_factory=list)
    completed_validation_modes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    @property
    def stage(self) -> str:
        if not self.diagnostics_complete:
            return "static_diagnostics"
        if self.script_change and not self.reload_complete:
            return "recompile_or_hot_reload"
        if not self.validation_complete:
            return "runtime_validation"
        return "complete"


class UnityAciController:
    """Gate Unity mutations behind evidence, checkpoints, diagnostics, and validation."""

    def __init__(
        self,
        context: ContextAssembler,
        *,
        project_root: Path,
        artifact_root: Path | None = None,
        config: AciConfig | dict[str, Any] | None = None,
        query_executor: StructuredQueryExecutor | None = None,
        mutation_executor: UnityMutationExecutor | None = None,
    ) -> None:
        self.context = context
        self.config = config if isinstance(config, AciConfig) else AciConfig(**(config or {}))
        self.query_executor = query_executor or StructuredQueryExecutor(
            context,
            project_root=project_root,
            artifact_root=artifact_root,
        )
        self.mutation_executor = mutation_executor or UnityMutationExecutor(
            project_root=project_root,
            artifact_root=artifact_root,
            config=self.config,
        )
        self.pending: PendingChange | None = None
        self.completed: list[dict[str, Any]] = []
        self.blocked_actions = 0

    def reset(self) -> None:
        self.pending = None
        self.completed = []
        self.blocked_actions = 0

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = str(action.get("tool", ""))
        if tool in QUERY_TOOL_NAMES:
            output = self.query_executor.execute(action)
            self._consume_query(tool, output)
            return output
        if tool in MUTATION_TOOL_NAMES:
            blocked = self._guard_mutation(tool, action.get("arguments", {}))
            if blocked:
                return blocked
            output = self.mutation_executor.execute(action)
            if self._succeeded(output):
                extra = output.get("extra", {})
                self.pending = PendingChange(
                    transaction_id=uuid.uuid4().hex[:12],
                    tool=tool,
                    checkpoint_id=str(extra.get("checkpoint_id", "")),
                    changed_paths=[str(value) for value in extra.get("changed_paths", [])],
                    script_change=tool in {"unity_script_patch", "unity_execute_csharp"},
                    required_validation_modes=list(self.config.required_validation_modes),
                )
                output.setdefault("extra", {})["execution_protocol"] = self.protocol_state()
            return output
        if tool in CONTROL_TOOL_NAMES:
            blocked = self._guard_control(tool, action.get("arguments", {}))
            if blocked:
                return blocked
            output = self.mutation_executor.execute(action)
            self._consume_control(tool, output)
            output.setdefault("extra", {})["execution_protocol"] = self.protocol_state()
            return output
        return self._blocked(tool, "unknown_aci_tool", f"Unknown ACI tool: {tool}")

    def guard_submission(self) -> dict[str, Any] | None:
        if self.pending is None:
            return None
        return self._blocked(
            "submit",
            "execution_protocol_incomplete",
            f"Cannot submit while checkpoint {self.pending.checkpoint_id} awaits {self.pending.stage}.",
        )

    def protocol_state(self) -> dict[str, Any]:
        return {
            "pending": asdict(self.pending) | {"stage": self.pending.stage} if self.pending else None,
            "completed_transactions": len(self.completed),
            "blocked_actions": self.blocked_actions,
            **self.mutation_executor.metrics(),
        }

    def metrics(self) -> dict[str, Any]:
        return self.protocol_state()

    def _guard_mutation(self, tool: str, args: Any) -> dict[str, Any] | None:
        if self.pending is not None:
            return self._blocked(
                tool,
                "previous_change_unverified",
                f"Checkpoint {self.pending.checkpoint_id} must finish {self.pending.stage} before another mutation.",
            )
        if not isinstance(args, dict):
            return self._blocked(tool, "invalid_arguments", "Arguments must be an object.")
        node_ids = args.get("evidence_node_ids", [])
        if not isinstance(node_ids, list) or not node_ids:
            return self._blocked(tool, "location_evidence_required", "evidence_node_ids must be non-empty.")
        requested = {str(value) for value in node_ids if value}
        store = self.context.project_store
        stale = requested.intersection(store.dirty_nodes) if store is not None else set()
        if stale:
            return self._blocked(
                tool,
                "stale_target_read_required",
                f"Rebuild the project graph and read stale target node(s) again: {', '.join(sorted(stale))}.",
            )
        active = [
            evidence
            for evidence in self.context.evidence.active()
            if requested.intersection(evidence.node_ids)
        ]
        located = {
            node_id
            for evidence in active
            for node_id in evidence.node_ids
            if node_id in requested
        }
        if self.config.require_location_evidence and located != requested:
            missing = sorted(requested - located)
            return self._blocked(
                tool,
                "location_evidence_required",
                f"No project-graph localization evidence exists for node(s): {', '.join(missing)}.",
            )
        read = {
            node_id
            for evidence in active
            if evidence.status in {EvidenceStatus.SOURCE_VERIFIED, EvidenceStatus.RUNTIME_VERIFIED}
            for node_id in evidence.node_ids
            if node_id in requested
        }
        if self.config.require_target_read and read != requested:
            missing = sorted(requested - read)
            return self._blocked(
                tool,
                "target_read_required",
                f"Read the target with unity_object_read, unity_asset_read, or code_file_read first: {', '.join(missing)}.",
            )
        return None

    def _guard_control(self, tool: str, args: Any) -> dict[str, Any] | None:
        if self.pending is None:
            return self._blocked(tool, "no_pending_change", "No checkpointed change is awaiting verification.")
        if tool in {"unity_recompile", "unity_hot_reload"}:
            if not self.pending.diagnostics_complete:
                return self._blocked(
                    tool,
                    "static_diagnostics_required",
                    "Run code_diagnostics successfully before reload.",
                )
            if not self.pending.script_change:
                return self._blocked(tool, "reload_not_required", "The pending typed asset change does not require reload.")
        if tool == "unity_validate":
            if not self.pending.diagnostics_complete:
                return self._blocked(
                    tool,
                    "static_diagnostics_required",
                    "Run code_diagnostics successfully before Unity validation.",
                )
            if self.pending.script_change and not self.pending.reload_complete:
                return self._blocked(
                    tool,
                    "reload_required",
                    "Run unity_recompile or a successful unity_hot_reload before validation.",
                )
            modes = set(args.get("modes", [])) if isinstance(args, dict) else set()
            remaining = set(self.pending.required_validation_modes) - set(self.pending.completed_validation_modes)
            if not modes.intersection(remaining):
                return self._blocked(
                    tool,
                    "required_validation_modes",
                    f"Validation must include at least one pending mode: {', '.join(sorted(remaining))}.",
                )
        return None

    def _consume_query(self, tool: str, output: dict[str, Any]) -> None:
        if self.pending is None or tool != "code_diagnostics" or not self._succeeded(output):
            return
        structured = output.get("extra", {}).get("structured", {})
        if structured.get("status") == "unavailable":
            return
        diagnostics = structured.get("diagnostics", [])
        if any(str(item.get("severity", "")).casefold() == "error" for item in diagnostics):
            return
        self.pending.diagnostics_complete = True

    def _consume_control(self, tool: str, output: dict[str, Any]) -> None:
        if self.pending is None or not self._succeeded(output):
            return
        if tool in {"unity_recompile", "unity_hot_reload"}:
            self.pending.reload_complete = True
        elif tool == "unity_validate":
            modes = [str(value) for value in output.get("extra", {}).get("validation_modes", [])]
            self.pending.completed_validation_modes = list(
                dict.fromkeys([*self.pending.completed_validation_modes, *modes])
            )
            required = set(self.pending.required_validation_modes)
            self.pending.validation_complete = required <= set(self.pending.completed_validation_modes)
        if self.pending.stage == "complete":
            state = asdict(self.pending) | {"stage": "complete", "completed_at": time.time()}
            self.completed.append(state)
            self.context.record_verified_fact(
                f"Checkpoint {self.pending.checkpoint_id} completed diagnostics, reload policy, and "
                f"{', '.join(self.pending.required_validation_modes)} validation.",
                sources=[f"checkpoint:{self.pending.checkpoint_id}"],
                runtime_verified=True,
            )
            self.pending = None

    @staticmethod
    def _succeeded(output: dict[str, Any]) -> bool:
        structured = output.get("extra", {}).get("structured", {})
        return int(output.get("returncode", -1)) == 0 and structured.get("status") != "unavailable"

    def _blocked(self, tool: str, code: str, message: str) -> dict[str, Any]:
        self.blocked_actions += 1
        payload = {
            "status": "blocked",
            "tool": tool,
            "guard": code,
            "message": message,
            "execution_protocol": self.protocol_state(),
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": -2,
            "exception_info": message,
            "extra": {
                "aci": True,
                "blocked": True,
                "guard": code,
                "structured": payload,
            },
        }
