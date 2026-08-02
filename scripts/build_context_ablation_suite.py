from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs" / "ablation" / "group1-full.json"
OUTPUT = ROOT / "configs" / "context_ablation"
TASKS = (
    "state-event-publication",
    "options-sfx-button-listener",
    "delivery-result-subscription",
    "plates-scriptableobject-reference",
    "stove-progress-reference",
    "stove-visual-component",
)
SEEDS = (101, 202, 303, 404, 505)
CONDITIONS = {
    "C0": {},
    "C1": {"graph_retrieval_enabled": False},
    "C2": {"semantic_search_enabled": False},
    "C3": {"causal_edges_enabled": False},
    "C4": {"context_assembly_enabled": False},
}


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    for condition, overrides in CONDITIONS.items():
        config = copy.deepcopy(source)
        config.pop("ablation_group", None)
        config["context_condition"] = condition
        config["experiment"]["config_id"] = f"kitchen-chaos-context-{condition.lower()}"
        config["experiment"]["task_language"] = "en"
        config["experiment"]["max_total_tokens"] = 163840
        config["context"]["enabled"] = True
        config["context"].update({
            "graph_retrieval_enabled": True,
            "semantic_search_enabled": True,
            "causal_edges_enabled": True,
            "context_assembly_enabled": True,
        })
        config["context"].update(overrides)
        _write(OUTPUT / f"{condition.lower()}.json", config)

    pilot = [
        {"condition": "C0", "task_id": task, "seed": 101}
        for task in TASKS
    ] + [
        {"condition": "C1", "task_id": "stove-progress-reference", "seed": 101},
        {"condition": "C2", "task_id": "options-sfx-button-listener", "seed": 101},
        {"condition": "C3", "task_id": "state-event-publication", "seed": 101},
        {"condition": "C4", "task_id": "delivery-result-subscription", "seed": 101},
    ]
    _write(OUTPUT / "pilot-schedule.json", {"schema_version": "context-ablation-schedule-v1", "runs": pilot})

    formal = [
        {"condition": condition, "task_id": task, "seed": seed}
        for seed in SEEDS for task in TASKS for condition in CONDITIONS
    ]
    random.Random(20260802).shuffle(formal)
    _write(OUTPUT / "formal-schedule.json", {"schema_version": "context-ablation-schedule-v1", "runs": formal})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    build()
