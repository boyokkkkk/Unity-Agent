from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from game_agent.context import ContextAssembler, EvidenceLedger


@dataclass(slots=True)
class UnresolvedSlot:
    id: str
    description: str
    status: str = "open"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompletedAction:
    signature: str
    tool: str
    claim: str
    result_sha256: str = ""
    evidence_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ActionDecision:
    allowed: bool
    signature: str
    reason: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)


class EvidenceActionCompiler:
    """Compile durable evidence into action masks and structured recovery options."""

    def __init__(self, context: ContextAssembler, *, project_root: Path) -> None:
        self.context = context
        self.project_root = project_root.resolve()
        self.completed_actions: dict[str, CompletedAction] = {}
        self.disabled_actions: dict[str, str] = {}
        self.unresolved_slots: dict[str, UnresolvedSlot] = {}
        self.last_observations: dict[str, dict[str, Any]] = {}
        self.last_admissible_signatures: list[str] = []
        self.search_candidates: dict[str, dict[str, Any]] = {}
        self.search_sequence = 0
        self.replan_count = 0
        self.reset()

    def reset(self) -> None:
        self.completed_actions = {}
        self.disabled_actions = {}
        self.last_observations = {}
        self.last_admissible_signatures = []
        self.search_candidates = {}
        self.search_sequence = 0
        self.replan_count = 0
        self.unresolved_slots = {
            "localized_target": UnresolvedSlot(
                "localized_target",
                "Identify at least one graph-backed target relevant to the task.",
            ),
            "implementation_source": UnresolvedSlot(
                "implementation_source",
                "Read at least one non-test implementation source for the root-cause path.",
            ),
        }

    def before_action(self, action: dict[str, Any]) -> ActionDecision:
        signature = self.action_signature(action)
        reason = self.disabled_actions.get(signature, "")
        if not reason:
            return ActionDecision(True, signature)
        return ActionDecision(
            False,
            signature,
            reason,
            self.admissible_alternatives(action, signature=signature),
        )

    def observe(self, action: dict[str, Any], output: dict[str, Any]) -> None:
        signature = self.action_signature(action)
        extra = output.get("extra", {})
        structured = extra.get("structured", {})
        tool = str(action.get("tool", ""))
        success = self._semantic_success(tool, action, output)
        self.last_observations[signature] = structured if isinstance(structured, dict) else {}
        if not success:
            if tool == "code_file_read":
                self._open_slot(
                    "failed_source_read",
                    "The requested source read failed; retry only after correcting its path or range.",
                )
            return

        self._remember_search_candidates(tool, action, structured)
        evidence_ids = [str(value) for value in extra.get("evidence_ids", []) if value]
        claim = str(extra.get("evidence_claim", "")).strip() or f"{tool} completed successfully."
        sources = [str(value) for value in extra.get("evidence_sources", []) if value]
        if extra.get("evidence_claim") and not evidence_ids:
            evidence_ids.append(
                EvidenceLedger.id_for(claim, sources or [f"aci:{tool}"])
            )
        result_sha = str(
            structured.get("sha256", "")
            or extra.get("output_sha256", "")
        )
        self.completed_actions[signature] = CompletedAction(
            signature=signature,
            tool=tool,
            claim=claim,
            result_sha256=result_sha,
            evidence_ids=evidence_ids,
        )
        if tool == "code_file_read":
            self.disabled_actions[signature] = (
                "The same source range at the same file SHA has already been read successfully."
            )
            self._resolve_slot("localized_target", evidence_ids)
            path = str(structured.get("path", "") or self._action_path(action))
            if self._is_explicit_implementation_read(action, structured, evidence_ids):
                self._resolve_slot("implementation_source", evidence_ids)
                self.unresolved_slots.pop("failed_source_read", None)
        elif tool in {
            "code_symbol_search",
            "code_find_references",
            "unity_asset_search",
            "unity_object_search",
            "unity_ref_search",
        } and extra.get("node_ids"):
            self._resolve_slot("localized_target", evidence_ids)
        elif extra.get("aci_mutation"):
            self._open_slot(
                "validation_evidence",
                "Complete diagnostics, reload policy, and required runtime validation.",
            )
        elif extra.get("aci_control") and tool == "unity_validate":
            self._resolve_slot("validation_evidence", evidence_ids)

    def action_signature(self, action: dict[str, Any]) -> str:
        tool = str(action.get("tool", ""))
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}
        if tool == "code_file_read":
            path = self._action_path(action)
            start = max(1, int(arguments.get("start_line", 1)))
            requested_end = arguments.get("end_line")
            end = str(int(requested_end)) if requested_end is not None else "*"
            sha = self._current_sha(path)
            return f"{tool}:{path}:{start}-{end}:{sha or 'missing'}"
        payload = json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return f"{tool}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"

    def replan_output(
        self,
        action: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        self.replan_count += 1
        signature = self.action_signature(action)
        observed = self.last_observations.get(signature, {})
        alternatives = self.admissible_alternatives(action, signature=signature)
        self.last_admissible_signatures = [
            self.action_signature(candidate) for candidate in alternatives
        ]
        payload = {
            "status": "replan",
            "tool": str(action.get("tool", "")),
            "location": {
                "path": self._action_path(action),
                "node_ids": _values(
                    action.get("arguments", {}).get("node_id", "")
                    if isinstance(action.get("arguments"), dict) else ""
                ),
            },
            "observed": {
                key: observed.get(key)
                for key in ("path", "sha256", "start_line", "end_line", "total_lines")
                if key in observed
            },
            "blocked_action": signature,
            "blocked_reason": reason,
            "unresolved_slots": self.open_slots(),
            "admissible_next_actions": alternatives,
        }
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": -2,
            "exception_info": reason,
            "extra": {
                "aci": True,
                "blocked": True,
                "replan": True,
                "guard": "completed_action_disabled",
                "action_signature": signature,
                "admissible_action_signatures": [
                    self.action_signature(candidate) for candidate in alternatives
                ],
                "structured": payload,
            },
        }

    def admissible_alternatives(
        self,
        action: dict[str, Any],
        *,
        signature: str = "",
    ) -> list[dict[str, Any]]:
        del signature
        alternatives: list[dict[str, Any]] = []
        tool = str(action.get("tool", ""))
        current_path = self._action_path(action)
        current_signature = self.action_signature(action)
        observed = self.last_observations.get(current_signature, {})
        if tool == "code_file_read":
            end = int(observed.get("end_line", 0) or 0)
            total = int(observed.get("total_lines", 0) or 0)
            if current_path and end and end < total:
                alternatives.append(
                    {
                        "tool": "code_file_read",
                        "arguments": {
                            "path": current_path,
                            "start_line": end + 1,
                            "end_line": min(total, end + 200),
                        },
                    }
                )
            for row in self._ranked_source_candidates(current_path):
                candidate = {
                    "tool": "code_file_read",
                    "arguments": {
                        "node_id": str(row.get("node_id", "")),
                        "path": str(row.get("path", "")),
                    },
                }
                if self.action_signature(candidate) not in self.disabled_actions:
                    alternatives.append(candidate)
                if len(alternatives) >= 3:
                    break
            node_ids = _values(observed.get("node", {}).get("id", "")) if isinstance(
                observed.get("node"), dict
            ) else []
            if node_ids:
                alternatives.append(
                    {
                        "tool": "code_find_references",
                        "arguments": {"node_id": node_ids[0], "direction": "both"},
                    }
                )
        if not alternatives:
            alternatives.append(
                {
                    "tool": "code_symbol_search",
                    "arguments": {
                        "query": self.context.original_task[:240],
                        "limit": 5,
                    },
                }
            )
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in alternatives:
            candidate_signature = self.action_signature(candidate)
            if candidate_signature not in seen and candidate_signature not in self.disabled_actions:
                seen.add(candidate_signature)
                unique.append(candidate)
        return unique[:3]

    def open_slots(self) -> list[dict[str, Any]]:
        return [
            asdict(slot)
            for slot in self.unresolved_slots.values()
            if slot.status == "open"
        ]

    def state(self) -> dict[str, Any]:
        return {
            "completed_actions": [
                asdict(item) for item in self.completed_actions.values()
            ],
            "disabled_actions": [
                {"signature": signature, "reason": reason}
                for signature, reason in self.disabled_actions.items()
            ],
            "unresolved_slots": self.open_slots(),
            "replan_count": self.replan_count,
            "admissible_action_signatures": self.last_admissible_signatures,
        }

    def _action_path(self, action: dict[str, Any]) -> str:
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            return ""
        path = str(arguments.get("path", "")).replace("\\", "/")
        if path:
            return path
        node_id = str(arguments.get("node_id", ""))
        store = self.context.project_store
        node = store.graph.nodes.get(node_id) if store is not None else None
        return node.path.replace("\\", "/") if node is not None else ""

    def _current_sha(self, path: str) -> str:
        if not path:
            return ""
        target = (self.project_root / path).resolve()
        try:
            target.relative_to(self.project_root)
        except ValueError:
            return ""
        if not target.is_file():
            return ""
        return hashlib.sha256(target.read_bytes()).hexdigest()

    def _semantic_success(
        self,
        tool: str,
        action: dict[str, Any],
        output: dict[str, Any],
    ) -> bool:
        if int(output.get("returncode", -1)) != 0:
            return False
        extra = output.get("extra", {})
        structured = extra.get("structured", {})
        if not isinstance(structured, dict):
            return False
        if structured.get("status") in {"error", "unavailable", "blocked", "replan"}:
            return False
        if tool == "code_file_read":
            path = str(structured.get("path", "")).replace("\\", "/")
            sha = str(structured.get("sha256", ""))
            content = str(structured.get("content", ""))
            start = int(structured.get("start_line", 0) or 0)
            end = int(structured.get("end_line", 0) or 0)
            total = int(structured.get("total_lines", 0) or 0)
            target = (self.project_root / path).resolve() if path else self.project_root
            try:
                target.relative_to(self.project_root)
            except ValueError:
                return False
            return bool(
                path
                and target.is_file()
                and re.fullmatch(r"[0-9a-fA-F]{64}", sha)
                and content
                and 1 <= start <= end <= total
                and str(extra.get("evidence_claim", "")).strip()
                and extra.get("evidence_sources")
            )
        if tool in {
            "code_symbol_search",
            "code_find_references",
            "unity_asset_search",
            "unity_object_search",
            "unity_ref_search",
        }:
            results = structured.get("results", [])
            return bool(
                isinstance(results, list)
                and results
                and extra.get("node_ids")
                and str(extra.get("evidence_claim", "")).strip()
            )
        if str(extra.get("evidence_claim", "")).strip():
            return bool(extra.get("evidence_sources") or extra.get("node_ids"))
        return True

    def _remember_search_candidates(
        self,
        tool: str,
        action: dict[str, Any],
        structured: dict[str, Any],
    ) -> None:
        if tool not in {
            "code_symbol_search",
            "code_find_references",
            "unity_asset_search",
            "unity_object_search",
            "unity_ref_search",
        }:
            return
        arguments = action.get("arguments", {})
        query = str(arguments.get("query", "") if isinstance(arguments, dict) else "")
        for rank, row in enumerate(structured.get("results", []), start=1):
            if not isinstance(row, dict):
                continue
            path = str(row.get("path", "")).replace("\\", "/")
            node_id = str(row.get("id", "") or row.get("node_id", ""))
            if not path or not node_id or _path_role(path) != "implementation":
                continue
            self.search_sequence += 1
            candidate = {
                "node_id": node_id,
                "path": path,
                "name": str(row.get("name", "")),
                "kind": str(row.get("kind", "")),
                "query": query or str(structured.get("query", "")),
                "rank": rank,
                "sequence": self.search_sequence,
                "source": "search",
            }
            previous = self.search_candidates.get(path.casefold())
            if previous is None or self._prefer_candidate(candidate, previous):
                self.search_candidates[path.casefold()] = candidate

    def _is_explicit_implementation_read(
        self,
        action: dict[str, Any],
        structured: dict[str, Any],
        evidence_ids: list[str],
    ) -> bool:
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            return False
        node_id = str(arguments.get("node_id", ""))
        path = str(structured.get("path", "")).replace("\\", "/")
        if not node_id or not path or not evidence_ids or _path_role(path) != "implementation":
            return False
        node = structured.get("node", {})
        observed_node_id = str(node.get("id", "")) if isinstance(node, dict) else ""
        if observed_node_id and observed_node_id != node_id:
            return False
        known_ids = {
            str(candidate.get("node_id", ""))
            for candidate in self.search_candidates.values()
            if _same_path(str(candidate.get("path", "")), path)
        }
        known_ids.update(
            entry.node_id
            for entry in self.context.working_set.entries.values()
            if _same_path(entry.path, path)
        )
        return node_id in known_ids

    def _ranked_source_candidates(self, current_path: str) -> list[dict[str, Any]]:
        by_path = dict(self.search_candidates)
        for entry in self.context.working_set.entries.values():
            path = entry.path.replace("\\", "/")
            if not path or _path_role(path) != "implementation":
                continue
            row = {
                "node_id": entry.node_id,
                "path": path,
                "name": entry.name,
                "kind": str(entry.kind),
                "query": "",
                "rank": 999,
                "sequence": 0,
                "source": "working_set",
                "relevance": entry.relevance,
            }
            key = path.casefold()
            if key not in by_path:
                by_path[key] = row
        rows = [
            row for row in by_path.values()
            if not _same_path(str(row.get("path", "")), current_path)
        ]
        rows.sort(key=lambda row: self._candidate_sort_key(row, current_path))
        return rows

    def _candidate_sort_key(
        self,
        row: dict[str, Any],
        current_path: str,
    ) -> tuple[float, float, int, str]:
        requested = Path(current_path).stem.casefold()
        candidate = Path(str(row.get("path", ""))).stem.casefold()
        similarity = SequenceMatcher(None, requested, candidate).ratio() if requested else 0.0
        if requested and (requested in candidate or candidate in requested):
            similarity += 1.0
        kind_bonus = 0.2 if str(row.get("kind", "")).upper() == "CSHARP_FILE" else 0.0
        search_bonus = 0.3 if row.get("source") == "search" else 0.0
        relevance = float(row.get("relevance", 0.0) or 0.0)
        rank = int(row.get("rank", 999) or 999)
        return (
            -(similarity + kind_bonus + search_bonus),
            -relevance,
            rank,
            str(row.get("path", "")).casefold(),
        )

    @staticmethod
    def _prefer_candidate(candidate: dict[str, Any], previous: dict[str, Any]) -> bool:
        candidate_file = str(candidate.get("kind", "")).upper() == "CSHARP_FILE"
        previous_file = str(previous.get("kind", "")).upper() == "CSHARP_FILE"
        if candidate_file != previous_file:
            return candidate_file
        return int(candidate.get("sequence", 0)) > int(previous.get("sequence", 0))

    def _open_slot(self, slot_id: str, description: str) -> None:
        self.unresolved_slots[slot_id] = UnresolvedSlot(slot_id, description)

    def _resolve_slot(self, slot_id: str, evidence_ids: list[str]) -> None:
        slot = self.unresolved_slots.get(slot_id)
        if slot is None:
            return
        slot.status = "resolved"
        slot.evidence_ids = list(dict.fromkeys([*slot.evidence_ids, *evidence_ids]))


def _path_role(path: str) -> str:
    normalized = path.replace("\\", "/").casefold()
    if "/tests/" in f"/{normalized}/" or normalized.endswith("tests.cs"):
        return "test"
    return "implementation" if normalized.endswith(".cs") else "asset"


def _values(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if item not in (None, "")]


def _same_path(left: str, right: str) -> bool:
    return left.replace("\\", "/").casefold() == right.replace("\\", "/").casefold()
