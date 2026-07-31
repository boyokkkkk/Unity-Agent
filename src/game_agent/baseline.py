from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from game_agent.context import EvidenceLedger


STAGE_METRICS_SCHEMA_VERSION = "game-agent-stage-metrics-v2"
CONVERSATION_SCHEMA_VERSION = "game-agent-conversation-v1"

_QUOTED_FILE = re.compile(
    r"""["']([^"']+\.(?:cs|asmdef|unity|prefab|asset|json|xml|log|md))["']""",
    re.IGNORECASE,
)
_PROJECT_FILE = re.compile(
    r"""((?:Assets|Packages)[\\/][^\s"'|;,]+\.(?:cs|asmdef|unity|prefab|asset|json|xml|log|md))""",
    re.IGNORECASE,
)


def normalize_project_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    marker = normalized.casefold().find("/assets/")
    if marker >= 0:
        return normalized[marker + 1 :]
    marker = normalized.casefold().find("/packages/")
    if marker >= 0:
        return normalized[marker + 1 :]
    return normalized.lstrip("./")


def extract_command_paths(command: str) -> list[str]:
    """Extract stable Unity project paths without touching the filesystem."""
    paths = [*(_QUOTED_FILE.findall(command)), *(_PROJECT_FILE.findall(command))]
    unique: list[str] = []
    seen: set[str] = set()
    for value in paths:
        normalized = normalize_project_path(value)
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(normalized)
    return unique


def classify_command(command: str) -> str:
    normalized = " ".join(command.casefold().split())
    if any(marker in normalized for marker in ("-runtests", "-testplatform", "unity.exe", "dotnet test")):
        return "validation"
    if re.search(
        r"\b(set-content|add-content|out-file|remove-item|move-item|copy-item|apply_patch)\b"
        r"|file\]::write|writealltext|writealllines",
        normalized,
    ):
        return "write"
    if re.search(r"\b(rg|select-string|findstr|where\.exe)\b|get-childitem\b.*\b-recurse\b", normalized):
        return "search"
    if re.search(r"\b(get-content|type)\b", normalized):
        return "read"
    return "other"


def enrich_tool_event(command: str, output: dict[str, Any] | None = None) -> dict[str, Any]:
    output = output or {}
    preview = str(output.get("output", "") or "")
    return {
        "command_category": classify_command(command),
        "accessed_files": extract_command_paths(command),
        "observation_chars": len(preview),
        "observation_lines": len(preview.splitlines()),
    }


def _event_ms(event: dict[str, Any], origin_ns: int = 0) -> int:
    if "elapsed_ms" in event:
        return int(event["elapsed_ms"])
    if "monotonic_ns" in event:
        return max(0, (int(event["monotonic_ns"]) - origin_ns) // 1_000_000)
    timestamp = str(event.get("ts", ""))
    if timestamp:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return int(parsed.astimezone(timezone.utc).timestamp() * 1000)
    return int(event.get("seq", 0))


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _matches(path: str, expected: str) -> bool:
    normalized = normalize_project_path(path).casefold()
    target = normalize_project_path(expected).casefold()
    return normalized == target or normalized.endswith("/" + target) or normalized.endswith(target)


def _is_aci_tool(tool: str) -> bool:
    return (
        tool.startswith("unity_")
        or tool.startswith("code_")
        or tool == "artifact_read"
    )


def _values(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return [str(item) for item in values if item not in (None, "")]


def _nested_paths(value: object) -> list[str]:
    paths: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"path", "asset_path", "source_path", "artifact_ref"}:
                paths.extend(_values(item))
            elif key in {"node", "asset", "object", "results"}:
                paths.extend(_nested_paths(item))
    elif isinstance(value, list):
        for item in value:
            paths.extend(_nested_paths(item))
    return [normalize_project_path(path) for path in paths]


def replay_aci_tool_events(
    trajectory: dict[str, Any],
    *,
    seq_start: int = 0,
) -> list[dict[str, Any]]:
    """Rebuild missing ACI tool pairs from a legacy trajectory's messages."""
    messages = list(trajectory.get("messages", []))
    replayed: list[dict[str, Any]] = []
    sequence = seq_start
    available_evidence_ids: list[str] = []
    available_evidence_node_ids: list[str] = []
    for index, message in enumerate(messages):
        actions = message.get("extra", {}).get("actions", [])
        if not isinstance(actions, list):
            continue
        observations: list[dict[str, Any]] = []
        for candidate in messages[index + 1 :]:
            if candidate.get("extra", {}).get("actions"):
                break
            if candidate.get("role") in {"tool", "user"}:
                observations.append(candidate)
            if len(observations) >= len(actions):
                break
        for offset, action in enumerate(actions):
            tool = str(action.get("tool", ""))
            if not _is_aci_tool(tool):
                continue
            arguments = action.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            encoded = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            arguments_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
            signature = f"{tool}:{arguments_hash}"
            observation = observations[offset] if offset < len(observations) else {}
            extra = dict(observation.get("extra", {}))
            claim = str(extra.get("evidence_claim", "")).strip()
            sources = _values(extra.get("evidence_sources", []))
            evidence_ids = (
                [EvidenceLedger.id_for(claim, sources or [f"aci:{tool}"])]
                if claim else []
            )
            paths = [
                *_values(arguments.get("path", "")),
                *_values(arguments.get("asset_path", "")),
                *_values(arguments.get("target_paths", [])),
                *_nested_paths(extra.get("structured", {})),
                *_values(extra.get("changed_paths", [])),
            ]
            common = {
                "aci": True,
                "telemetry_source": "trajectory_replay",
                "tool": tool,
                "tool_call_id": str(action.get("tool_call_id", "") or ""),
                "tool_class": (
                    "mutation" if extra.get("aci_mutation")
                    else "validation" if extra.get("aci_control")
                    else "query"
                ),
                "arguments_hash": arguments_hash,
                "action_signature": signature,
                "node_ids": _values(extra.get("node_ids", [])),
                "changed_paths": _values(extra.get("changed_paths", [])),
                "accessed_files": list(dict.fromkeys(normalize_project_path(path) for path in paths)),
                "evidence_ids": evidence_ids,
                "available_evidence_ids": list(available_evidence_ids),
                "available_evidence_node_ids": list(available_evidence_node_ids),
                "referenced_node_ids": [
                    *_values(arguments.get("evidence_node_ids", [])),
                    *_values(arguments.get("node_id", "")),
                ],
                "stale_evidence_node_ids": [],
                "evidence_expected": bool(claim),
                "replayed": True,
            }
            sequence += 1
            replayed.append({"seq": sequence, "event": "tool_start", **common})
            sequence += 1
            replayed.append(
                {
                    "seq": sequence,
                    "event": "tool_end",
                    **common,
                    "returncode": int(extra.get("returncode", -1)),
                    "blocked": bool(extra.get("blocked", False)),
                    "blocked_reason": str(extra.get("guard", "") or ""),
                    "output_chars": int(extra.get("output_chars", 0) or 0),
                    "output_sha256": str(extra.get("output_sha256", "") or ""),
                }
            )
            available_evidence_ids = list(dict.fromkeys([*available_evidence_ids, *evidence_ids]))
            available_evidence_node_ids = list(
                dict.fromkeys(
                    [*available_evidence_node_ids, *_values(extra.get("node_ids", []))]
                )
            )
    return replayed


class StageAnalyzer:
    """Reconstruct deterministic experiment stages from append-only events."""

    def __init__(self, *, relevant_files: Iterable[str], root_cause_file: str) -> None:
        self.relevant_files = tuple(normalize_project_path(path) for path in relevant_files)
        self.root_cause_file = normalize_project_path(root_cause_file)

    def analyze(
        self,
        events: Iterable[dict[str, Any]],
        *,
        trajectory: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        records = [dict(event) for event in events]
        if trajectory and not any(event.get("telemetry_source") == "aci" for event in records):
            replayed = replay_aci_tool_events(
                trajectory,
                seq_start=max((int(event.get("seq", 0)) for event in records), default=0),
            )
            model_end_times = [
                _event_ms(event)
                for event in records
                if event.get("event") == "model_end"
            ]
            next_model_times = [
                _event_ms(event)
                for event in records
                if event.get("event") == "model_start"
            ][1:]
            for call_index in range(0, len(replayed), 2):
                model_index = call_index // 2
                if model_index < len(model_end_times):
                    replayed[call_index]["elapsed_ms"] = model_end_times[model_index]
                    replayed[call_index + 1]["elapsed_ms"] = (
                        next_model_times[model_index]
                        if model_index < len(next_model_times)
                        else model_end_times[model_index]
                    )
            records.extend(replayed)
        records.sort(key=lambda item: int(item.get("seq", 0)))
        origin_ns = min((int(item["monotonic_ns"]) for item in records if "monotonic_ns" in item), default=0)
        timed = [(event, _event_ms(event, origin_ns)) for event in records]

        def first_time(predicate) -> int | None:
            return next((when for event, when in timed if predicate(event)), None)

        def last_time(predicate) -> int | None:
            values = [when for event, when in timed if predicate(event)]
            return values[-1] if values else None

        file_sequence: list[str] = []
        for event, _ in timed:
            paths = list(event.get("accessed_files") or [])
            if not paths and event.get("command"):
                paths = extract_command_paths(str(event["command"]))
            for path in paths:
                normalized = normalize_project_path(str(path))
                if normalized.casefold() not in {item.casefold() for item in file_sequence}:
                    file_sequence.append(normalized)

        def event_hits(event: dict[str, Any], expected: str) -> bool:
            paths = list(event.get("accessed_files") or [])
            if not paths and event.get("command"):
                paths = extract_command_paths(str(event["command"]))
            return any(_matches(str(path), expected) for path in paths)

        t0 = first_time(lambda event: event.get("event") == "turn_start")
        if t0 is None:
            t0 = first_time(lambda event: event.get("event") == "task_start")
        t0 = t0 if t0 is not None else (timed[0][1] if timed else 0)
        t1 = first_time(lambda event: event.get("event") == "tool_start")
        t2 = first_time(
            lambda event: any(event_hits(event, relevant) for relevant in self.relevant_files)
        )
        t3 = first_time(lambda event: event_hits(event, self.root_cause_file))
        t4 = first_time(
            lambda event: event.get("event") == "tool_end"
            and event.get("returncode", 0) == 0
            and (event.get("command_category") or classify_command(str(event.get("command", "")))) == "write"
        )
        t5 = first_time(
            lambda event: event.get("event") == "diff_snapshot" and bool(event.get("oracle_match"))
        )
        t6 = first_time(
            lambda event: event.get("event") == "validation_start"
            or (
                event.get("event") == "tool_start"
                and (event.get("command_category") or classify_command(str(event.get("command", ""))))
                == "validation"
            )
        )
        t7 = first_time(lambda event: event.get("event") == "turn_end")
        if t7 is None:
            t7 = last_time(lambda event: event.get("event") in {"agent_limit_reached", "task_end"})
        t7 = t7 if t7 is not None else (timed[-1][1] if timed else t0)
        t8 = last_time(
            lambda event: event.get("event") == "validation_end"
            and event.get("validation_scope", "public") == "public"
        )
        t9 = last_time(
            lambda event: event.get("event") == "validation_end"
            and event.get("validation_scope") == "hidden"
        )

        milestones = {
            "T0_task_submitted": t0,
            "T1_first_tool": t1,
            "T2_first_relevant_file": t2,
            "T3_root_cause_file": t3,
            "T4_first_edit": t4,
            "T5_first_correct_patch": t5,
            "T6_first_validation": t6,
            "T7_agent_stopped": t7,
            "T8_public_validation_end": t8,
            "T9_hidden_validation_end": t9,
        }

        def bounded_duration(start: int | None, end: int | None, fallback: int) -> int:
            actual_start = fallback if start is None else start
            actual_end = t7 if end is None else end
            return max(0, actual_end - actual_start)

        stages = {
            "task_understanding": bounded_duration(t0, t1, t0),
            "source_localization": bounded_duration(t1, t3, t0),
            "diagnosis": bounded_duration(t3, t4, t1 or t0),
            "editing": bounded_duration(t4, t6, t3 or t1 or t0),
            "self_validation": bounded_duration(t6, t7, t4 or t3 or t1 or t0),
            "public_validation": max(0, (t8 or t7) - t7) if t8 is not None else 0,
            "hidden_validation": max(0, (t9 or t8 or t7) - (t8 or t7)) if t9 is not None else 0,
        }

        relevant_hits = {
            relevant
            for relevant in self.relevant_files
            if any(_matches(path, relevant) for path in file_sequence)
        }
        relevant_accesses = sum(
            1 for path in file_sequence if any(_matches(path, relevant) for relevant in self.relevant_files)
        )
        root_rank = next(
            (index for index, path in enumerate(file_sequence, start=1) if _matches(path, self.root_cause_file)),
            None,
        )

        tool_ends = [event for event in records if event.get("event") == "tool_end"]
        raw_chars = sum(int(event.get("output_chars", event.get("observation_chars", 0)) or 0) for event in tool_ends)
        retained_chars = sum(int(event.get("observation_chars", len(str(event.get("output", "")))) or 0) for event in tool_ends)
        seen_digests: set[str] = set()
        repeated_chars = 0
        for event in tool_ends:
            digest = str(event.get("output_sha256", ""))
            size = int(event.get("output_chars", event.get("observation_chars", 0)) or 0)
            if digest and digest in seen_digests:
                repeated_chars += size
            if digest:
                seen_digests.add(digest)

        usage = [event for event in records if event.get("event") == "model_usage"]
        preflight = [event for event in records if event.get("event") == "model_preflight"]
        tool_profile_calls: dict[str, int] = {}
        tool_profile_schema_tokens: dict[str, int] = {}
        for event in preflight:
            profile = str(event.get("tool_profile", "") or "unknown")
            tool_profile_calls[profile] = tool_profile_calls.get(profile, 0) + 1
            tool_profile_schema_tokens[profile] = (
                tool_profile_schema_tokens.get(profile, 0)
                + int(event.get("tool_schema_tokens", 0) or 0)
            )
        prompt_tokens = sum(int(event.get("prompt_tokens", 0) or 0) for event in usage)
        completion_tokens = sum(int(event.get("completion_tokens", 0) or 0) for event in usage)
        total_tokens = max((int(event.get("total_tokens", 0) or 0) for event in usage), default=0)
        if trajectory:
            stats = trajectory.get("info", {}).get("model_stats", {})
            prompt_tokens = int(stats.get("prompt_tokens", prompt_tokens) or 0)
            completion_tokens = int(stats.get("completion_tokens", completion_tokens) or 0)
            total_tokens = int(stats.get("total_tokens", total_tokens) or 0)

        commands = [
            " ".join(str(event.get("command", "")).split()).casefold()
            for event in records
            if event.get("event") == "tool_start"
            and str(event.get("command", "")).strip()
        ]
        repeated_commands = len(commands) - len(set(commands))
        writes_after_validation = sum(
            1
            for event, when in timed
            if t6 is not None
            and when > t6
            and event.get("event") == "tool_end"
            and event.get("returncode", 0) == 0
            and (event.get("command_category") or classify_command(str(event.get("command", "")))) == "write"
        )

        aci_starts = [
            event for event in records
            if event.get("event") == "tool_start" and bool(event.get("aci"))
        ]
        aci_ends = [
            event for event in records
            if event.get("event") == "tool_end" and bool(event.get("aci"))
        ]
        retrieval_paths = [
            normalize_project_path(str(path))
            for event in aci_ends
            if event.get("tool_class") == "query" and int(event.get("returncode", -1)) == 0
            for path in event.get("accessed_files", [])
            if str(path)
        ]
        retrieval_at_k = retrieval_paths[:4]
        distinct_at_k = {path.casefold() for path in retrieval_at_k}
        test_paths_at_k = [
            path for path in retrieval_at_k
            if "/tests/" in f"/{path.casefold()}/" or path.casefold().endswith("tests.cs")
        ]
        causal_observed = sum(int(event.get("causal_edges_observed", 0) or 0) for event in aci_ends)
        causal_total = sum(int(event.get("causal_edges_total", 0) or 0) for event in aci_ends)

        evidence_expected = [event for event in aci_ends if event.get("evidence_expected")]
        written_evidence = {
            str(evidence_id)
            for event in evidence_expected
            for evidence_id in event.get("evidence_ids", [])
            if evidence_id
        }
        evidence_transitions = 0
        evidence_presented = 0
        for end_event in aci_ends:
            produced = set(_values(end_event.get("evidence_ids", [])))
            if not produced:
                continue
            later = next(
                (
                    event for event in records
                    if int(event.get("seq", 0)) > int(end_event.get("seq", 0))
                    and event.get("event") == "tool_start"
                    and event.get("aci")
                ),
                None,
            )
            if later is None:
                continue
            evidence_transitions += len(produced)
            evidence_presented += len(produced.intersection(_values(later.get("available_evidence_ids", []))))

        utilization_denominator = 0
        utilized = 0
        stale_references = 0
        referenced_evidence_nodes = 0
        for event in aci_starts:
            available_nodes = set(_values(event.get("available_evidence_node_ids", [])))
            referenced_nodes = set(_values(event.get("referenced_node_ids", [])))
            if available_nodes and referenced_nodes:
                utilization_denominator += 1
                utilized += int(bool(available_nodes.intersection(referenced_nodes)))
            referenced_evidence_nodes += len(referenced_nodes)
            stale_references += len(_values(event.get("stale_evidence_node_ids", [])))

        signatures = [str(event.get("action_signature", "")) for event in aci_ends]
        duplicate_actions = len(signatures) - len(set(signatures))
        blocked_events = [event for event in aci_ends if event.get("blocked")]
        recovered = 0
        for blocked_event in blocked_events:
            blocked_signature = str(blocked_event.get("action_signature", ""))
            if any(
                int(candidate.get("seq", 0)) > int(blocked_event.get("seq", 0))
                and int(candidate.get("returncode", -1)) == 0
                and str(candidate.get("action_signature", "")) != blocked_signature
                for candidate in aci_ends
            ):
                recovered += 1
        admissible_events = [
            event for event in aci_starts if event.get("admissible_action_signatures")
        ]
        accepted_admissible = sum(
            str(event.get("action_signature", "")) in set(_values(event.get("admissible_action_signatures", [])))
            for event in admissible_events
        )
        mutation_events = [event for event in aci_ends if event.get("tool_class") == "mutation"]
        typed_mutations = [event for event in mutation_events if not event.get("escape_hatch")]
        escape_hatches = [event for event in mutation_events if event.get("escape_hatch")]
        completed_transactions = max(
            (
                int((event.get("execution_protocol") or {}).get("completed_transactions", 0) or 0)
                for event in aci_ends
                if isinstance(event.get("execution_protocol"), dict)
            ),
            default=0,
        )
        schema_tokens = sum(
            int(event.get("tool_schema_tokens", 0) or 0)
            for event in preflight
        )

        turn_end = next((event for event in records if event.get("event") == "turn_end"), {})
        limit_event = next((event for event in records if event.get("event") == "agent_limit_reached"), {})
        exit_status = str(turn_end.get("exit_status") or limit_event.get("limit") or "")
        submission = str(turn_end.get("submission", "") or "")

        return {
            "schema_version": STAGE_METRICS_SCHEMA_VERSION,
            "milestones_ms": milestones,
            "stage_duration_ms": stages,
            "phase_reentry": {"editing_after_validation": writes_after_validation},
            "outcome": {
                "agent_submitted": exit_status == "Submitted" and bool(submission.strip()),
                "exit_status": exit_status,
                "missing_final_answer": not bool(submission.strip()),
            },
            "navigation": {
                "files_accessed": file_sequence,
                "root_cause_rank": root_rank,
                "relevant_recall": _ratio(len(relevant_hits), len(self.relevant_files)),
                "navigation_precision": _ratio(relevant_accesses, len(file_sequence)),
                "unrelated_file_ratio": _ratio(len(file_sequence) - relevant_accesses, len(file_sequence)),
            },
            "context": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "peak_context_usage_percent": max(
                    (float(event.get("context_usage_percent", 0.0) or 0.0) for event in preflight),
                    default=0.0,
                ),
                "raw_output_chars": raw_chars,
                "retained_output_chars": retained_chars,
                "truncated_tool_calls": sum(bool(event.get("output_truncated")) for event in tool_ends),
                "repeated_observation_ratio": _ratio(repeated_chars, raw_chars),
            },
            "behavior": {
                "model_calls": len(usage),
                "tool_calls": len(tool_ends),
                "failed_tool_calls": sum(int(event.get("returncode", 0) or 0) != 0 for event in tool_ends),
                "repeated_commands": repeated_commands,
            },
            "research": {
                "retrieval": {
                    "k": 4,
                    "candidate_paths_at_k": len(retrieval_at_k),
                    "distinct_paths_at_k": len(distinct_at_k),
                    "distinct_path_ratio_at_k": _ratio(len(distinct_at_k), len(retrieval_at_k)),
                    "test_node_ratio_at_k": _ratio(len(test_paths_at_k), len(retrieval_at_k)),
                    "root_cause_mrr": _ratio(1, root_rank or 0),
                    "causal_edge_coverage": _ratio(causal_observed, causal_total),
                    "causal_edges_total": causal_total,
                },
                "memory": {
                    "evidence_write_recall": _ratio(
                        sum(bool(event.get("evidence_ids")) for event in evidence_expected),
                        len(evidence_expected),
                    ),
                    "evidence_read_recall": _ratio(evidence_presented, evidence_transitions),
                    "evidence_utilization": _ratio(utilized, utilization_denominator),
                    "stale_evidence_rate": _ratio(stale_references, referenced_evidence_nodes),
                    "unique_evidence": len(written_evidence),
                    "expected_evidence_writes": len(evidence_expected),
                    "evidence_read_transitions": evidence_transitions,
                    "evidence_utilization_opportunities": utilization_denominator,
                    "referenced_evidence_nodes": referenced_evidence_nodes,
                },
                "control": {
                    "duplicate_action_ratio": _ratio(duplicate_actions, len(aci_ends)),
                    "blocked_action_recovery_rate": _ratio(recovered, len(blocked_events)),
                    "admissible_action_acceptance": _ratio(
                        accepted_admissible, len(admissible_events)
                    ),
                    "phase_regression_count": writes_after_validation,
                    "protocol_gate_completion": _ratio(
                        completed_transactions, len(mutation_events)
                    ),
                    "blocked_actions": len(blocked_events),
                    "admissible_action_opportunities": len(admissible_events),
                    "mutation_calls": len(mutation_events),
                },
                "tools_and_cost": {
                    "aci_tool_calls": len(aci_ends),
                    "tool_schema_tokens_per_call": _ratio(schema_tokens, len(usage)),
                    "unique_evidence_per_1k_tokens": _ratio(
                        len(written_evidence) * 1000, total_tokens
                    ),
                    "typed_mutation_ratio": _ratio(len(typed_mutations), len(mutation_events)),
                    "escape_hatch_ratio": _ratio(len(escape_hatches), len(mutation_events)),
                    "tool_schema_measurements": sum(
                        int(event.get("tool_schema_tokens", 0) or 0) > 0
                        for event in preflight
                    ),
                    "tool_profile_calls": tool_profile_calls,
                    "tool_schema_tokens_by_profile": tool_profile_schema_tokens,
                },
            },
        }


def project_conversation(events: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create a deterministic user-facing transcript without model calls."""
    records = sorted((dict(event) for event in events), key=lambda item: int(item.get("seq", 0)))
    conversation: list[dict[str, Any]] = []
    emitted_progress: set[str] = set()
    terminal_event: dict[str, Any] | None = None

    def append(role: str, kind: str, content: str, event: dict[str, Any]) -> None:
        conversation.append(
            {
                "schema_version": CONVERSATION_SCHEMA_VERSION,
                "role": role,
                "kind": kind,
                "content": content,
                "source_seq": int(event.get("seq", 0)),
            }
        )

    for event in records:
        name = event.get("event")
        if name == "turn_start" and event.get("request"):
            append("user", "task", str(event["request"]), event)
        elif name == "tool_start":
            category = event.get("command_category") or classify_command(str(event.get("command", "")))
            message = {
                "search": ("localizing", "正在定位与状态切换和 UI 刷新相关的源码。"),
                "write": ("editing", "已经定位候选根因，正在进行最小范围修改。"),
                "validation": ("validating", "修改已形成，正在运行验证。"),
            }.get(str(category))
            if message and message[0] not in emitted_progress:
                emitted_progress.add(message[0])
                append("assistant", "progress", message[1], event)
        elif name == "validation_start" and "validating" not in emitted_progress:
            emitted_progress.add("validating")
            append("assistant", "progress", "修改已形成，正在运行验证。", event)
        elif name == "turn_end":
            terminal_event = event
    if terminal_event is not None:
        submission = str(terminal_event.get("submission", "") or "").strip()
        if submission:
            append("assistant", "final", submission, terminal_event)
        else:
            reason = str(terminal_event.get("exit_status") or terminal_event.get("status") or "unknown")
            append("system", "failure", f"任务未产生最终回答，停止原因：{reason}。", terminal_event)
    return conversation
