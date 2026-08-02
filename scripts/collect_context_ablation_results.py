from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def collect(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("baseline-report.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        treatment = report.get("treatment_activation", {})
        context = report.get("metrics", {}).get("context", {})
        rows.append({
            "run_id": report.get("run_id", path.parent.name),
            "condition": treatment.get("condition", ""),
            "task_id": report.get("task_id", ""),
            "difficulty": report.get("task_difficulty", ""),
            "experiment_valid": bool(report.get("experiment_valid")),
            "treatment_activated": bool(treatment.get("activated")),
            "verified_success": bool(report.get("verified_success")),
            "agent_submitted": bool(report.get("agent", {}).get("submitted")),
            "oracle_match": bool(report.get("oracle_match")),
            "total_tokens": int(context.get("total_tokens", 0) or 0),
            "model_calls": int(report.get("metrics", {}).get("behavior", {}).get("model_calls", 0) or 0),
            "report_path": str(path),
        })
    return rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["condition"], row["difficulty"])].append(row)
    summary = []
    for (condition, difficulty), items in sorted(groups.items()):
        valid = [item for item in items if item["experiment_valid"]]
        summary.append({
            "condition": condition,
            "difficulty": difficulty,
            "runs": len(items),
            "valid_runs": len(valid),
            "activation_rate": sum(item["treatment_activated"] for item in items) / len(items),
            "verified_success_rate_valid": (
                sum(item["verified_success"] for item in valid) / len(valid) if valid else 0.0
            ),
            "mean_tokens_valid": (
                sum(item["total_tokens"] for item in valid) / len(valid) if valid else 0.0
            ),
        })
    return summary


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/context-ablation-summary"))
    args = parser.parse_args()
    rows = collect(args.root)
    summary = summarize(rows)
    _write_csv(args.output.with_suffix(".runs.csv"), rows)
    _write_csv(args.output.with_suffix(".summary.csv"), summary)
    invalid = sum(not row["experiment_valid"] for row in rows)
    print(json.dumps({"runs": len(rows), "invalid": invalid, "summary_rows": len(summary)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
