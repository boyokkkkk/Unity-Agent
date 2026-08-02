from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs" / "kitchen_chaos.json"
DESTINATION = ROOT / "configs" / "ablation"

GROUPS: tuple[tuple[str, str, str, tuple[str, ...], object], ...] = (
    ("group1-full.json", "group1-full", "full_system", (), True),
    ("group2-no-p1.json", "group2-no-p1", "evidence_recovery", ("aci", "evidence_recovery_enabled"), False),
    ("group3-no-evidence.json", "group3-no-evidence", "evidence_artifact", ("aci", "evidence_artifact_enabled"), False),
    ("group4-no-dynamic-tools.json", "group4-no-dynamic-tools", "dynamic_tool_exposure", ("aci", "dynamic_tool_exposure_enabled"), False),
    ("group5-no-search-budget.json", "group5-no-search-budget", "bounded_search", ("aci", "bounded_search_enabled"), False),
    ("group6-no-graph.json", "group6-no-graph", "project_graph_retrieval", ("context", "enabled"), False),
    ("group7-no-contract.json", "group7-no-contract", "submission_contract", ("aci", "submission_contract_enabled"), False),
    ("group8-no-typed-mutations.json", "group8-no-typed-mutations", "typed_mutations", ("aci", "typed_mutations_enabled"), False),
    ("group9-no-validation.json", "group9-no-validation", "agent_validation_gates", ("aci", "validation_gates_enabled"), False),
)


def _set_nested(payload: dict, path: tuple[str, ...], value: object) -> None:
    cursor = payload
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value


def build() -> None:
    base = json.loads(SOURCE.read_text(encoding="utf-8"))
    base["experiment"].update(
        config_id="state-event-v1-ablation",
        max_total_tokens=81920,
        task_language="en",
    )
    base["context"]["graph_path"] = (
        "artifacts/project-graph/kitchen-chaos-causal-full/project-graph.json"
    )
    graph_path = ROOT / base["context"]["graph_path"]
    base["context"]["graph_sha256"] = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    base["aci"].update(
        evidence_artifact_enabled=True,
        evidence_recovery_enabled=True,
        bounded_search_enabled=True,
        project_graph_enabled=True,
        submission_contract_enabled=True,
        validation_gates_enabled=True,
        automatic_validation_enabled=True,
        required_validation_modes=["editmode", "playmode"],
    )
    base["validation"].update(
        enabled=True,
        modes=["compile", "editmode", "playmode"],
        timeout_seconds=1200,
    )
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for filename, group, factor, path, value in GROUPS:
        payload = copy.deepcopy(base)
        payload["ablation_group"] = group
        payload["ablation_factor"] = factor
        payload["ablation_treatment"] = "enabled" if not path else "disabled"
        if path:
            _set_nested(payload, path, value)
        (DESTINATION / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    build()
