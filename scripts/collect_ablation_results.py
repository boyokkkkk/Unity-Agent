from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


GROUP_NAMES = {
    1: "Full system (baseline)",
    2: "Without evidence-based recovery",
    3: "Without evidence artifact materialization",
    4: "Without dynamic tool exposure",
    5: "Without bounded search budget",
    6: "Without project graph retrieval",
    7: "Without submission contract",
    8: "Without typed mutations",
    9: "Without agent validation gates",
}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return events


def _successful_tool_ends(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event") == "tool_end"
        and int(event.get("returncode", 0) or 0) == 0
        and not bool(event.get("blocked", False))
    ]


def _execution_protocols(tool_ends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        protocol
        for event in tool_ends
        if isinstance((protocol := event.get("execution_protocol")), dict)
    ]


def _nested(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    value: Any = mapping
    for key in keys:
        if not isinstance(value, dict):
            return default
        value = value.get(key)
    return default if value is None else value


def collect_ablation_results(
    artifact_root: str | Path = "artifacts/baselines/state-event-v1",
) -> pd.DataFrame:
    artifact_path = Path(artifact_root)
    if not artifact_path.exists():
        print(f"Artifact directory not found: {artifact_path}")
        return pd.DataFrame()

    results: list[dict[str, Any]] = []
    for run_dir in sorted(artifact_path.iterdir()):
        if not run_dir.is_dir() or not run_dir.name.startswith("ablation-group"):
            continue

        try:
            parts = run_dir.name.split("-")
            group_num = int(parts[1].removeprefix("group"))
            run_num = int(parts[2].removeprefix("run"))

            agent_path = run_dir / "agent-result.json"
            report_path = run_dir / "baseline-report.json"
            metrics_path = run_dir / "stage-metrics.json"
            events_path = run_dir / "events.jsonl"
            if not agent_path.exists():
                print(f"Skipping {run_dir.name}: agent-result.json not found")
                continue

            agent = _read_json(agent_path)
            report = _read_json(report_path) if report_path.exists() else {}
            metrics = _read_json(metrics_path) if metrics_path.exists() else {}
            events = _read_events(events_path)
            tool_ends = _successful_tool_ends(events)
            protocols = _execution_protocols(tool_ends)

            token_usage = agent.get("token_usage") or {}
            context = metrics.get("context") or {}
            behavior = metrics.get("behavior") or {}
            control = _nested(metrics, "research", "control", default={})
            tools_cost = _nested(metrics, "research", "tools_and_cost", default={})
            outcome = metrics.get("outcome") or {}

            total_tokens = token_usage.get(
                "total_tokens", agent.get("total_tokens", context.get("total_tokens", 0))
            )
            prompt_tokens = token_usage.get(
                "prompt_tokens", agent.get("input_tokens", context.get("prompt_tokens", 0))
            )
            completion_tokens = token_usage.get(
                "completion_tokens", context.get("completion_tokens", 0)
            )

            max_round = max(
                (int(event.get("round", 0) or 0) for event in events),
                default=0,
            )
            rounds = max_round or int(behavior.get("model_calls", 0) or 0)

            completed_protocol_actions = [
                action
                for protocol in protocols
                for action in protocol.get("completed_actions", [])
                if isinstance(action, dict)
            ]
            completed_protocol_tools = {
                str(action.get("tool", "")) for action in completed_protocol_actions
            }
            successful_tools = {str(event.get("tool", "")) for event in tool_ends}

            mutation_calls = int(control.get("mutation_calls", 0) or 0)
            if not mutation_calls:
                mutation_calls = sum(
                    1
                    for event in tool_ends
                    if event.get("tool_class") == "mutation"
                    or event.get("tool") in {"patch_apply", "unity_script_patch"}
                )

            mutation_failures = sum(
                1
                for event in events
                if event.get("event") == "tool_end"
                and (
                    event.get("tool_class") == "mutation"
                    or event.get("tool") in {"patch_apply", "unity_script_patch"}
                )
                and (
                    int(event.get("returncode", 0) or 0) != 0
                    or bool(event.get("blocked", False))
                )
            )

            protocol_completion = control.get("protocol_gate_completion")
            typed_ratio = tools_cost.get("typed_mutation_ratio")
            escape_ratio = tools_cost.get("escape_hatch_ratio")
            if protocols:
                latest = protocols[-1]
                typed_calls = int(latest.get("typed_mutation_calls", 0) or 0)
                escape_calls = int(latest.get("escape_hatch_calls", 0) or 0)
                protocol_mutations = int(latest.get("mutation_transactions", 0) or 0)
                denominator = typed_calls + escape_calls
                if typed_ratio is None and denominator:
                    typed_ratio = typed_calls / denominator
                if escape_ratio is None and denominator:
                    escape_ratio = escape_calls / denominator
                if not mutation_calls:
                    mutation_calls = protocol_mutations

            reached_diagnose = bool(
                {"diagnosis_submit", "diagnosis_revise"} & successful_tools
            )
            reached_edit = mutation_calls > 0
            reached_validate = bool(
                {"unity_recompile", "unity_validate"}
                & (successful_tools | completed_protocol_tools)
            )
            reached_review = any(
                bool(_nested(protocol, "workflow", "reviews", default=[]))
                for protocol in protocols
            )
            reached_submit = bool(
                _nested(report, "agent", "submitted", default=outcome.get("agent_submitted", False))
            )

            result = {
                "group": group_num,
                "group_name": GROUP_NAMES.get(group_num, "Unknown"),
                "run": run_num,
                "run_id": run_dir.name,
                "exit_status": agent.get("exit_status", outcome.get("exit_status", "Unknown")),
                "experiment_valid": bool(report.get("experiment_valid", False)),
                "verified_success": bool(report.get("verified_success", False)),
                "source_unchanged": bool(report.get("source_project_unchanged", False)),
                "public_validation_passed": bool(report.get("public_validation_passed", False)),
                "hidden_validation_passed": bool(report.get("hidden_validation_passed", False)),
                "prompt_tokens": int(prompt_tokens or 0),
                "completion_tokens": int(completion_tokens or 0),
                "total_tokens": int(total_tokens or 0),
                "rounds": rounds,
                "model_calls": int(behavior.get("model_calls", 0) or 0),
                "tool_calls": int(behavior.get("tool_calls", 0) or 0),
                "mutation_calls": mutation_calls,
                "mutation_failures": mutation_failures,
                "typed_mutation_ratio": float(typed_ratio or 0.0),
                "escape_hatch_ratio": float(escape_ratio or 0.0),
                "protocol_gate_completion": float(protocol_completion or 0.0),
                "format_errors": sum(
                    1 for event in events if event.get("error_type") == "FormatError"
                ),
                "reached_diagnose": reached_diagnose,
                "reached_edit": reached_edit,
                "reached_validate": reached_validate,
                "reached_review": reached_review,
                "reached_submit": reached_submit,
                "artifact_complete": all(
                    path.exists()
                    for path in (agent_path, report_path, metrics_path, events_path)
                ),
            }
            results.append(result)
        except Exception as exc:
            print(f"Error processing {run_dir.name}: {exc}")

    if not results:
        print("No ablation results found")
        return pd.DataFrame()
    return pd.DataFrame(results).sort_values(["group", "run", "run_id"])


def analyze_ablation_results(
    df: pd.DataFrame,
    output_dir: str | Path = ".",
) -> tuple[Path, Path]:
    if df.empty:
        raise ValueError("No data to analyze")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    aggregations: dict[str, list[str] | str] = {
        "verified_success": ["mean", "sum", "count"],
        "experiment_valid": "mean",
        "total_tokens": ["mean", "std"],
        "rounds": ["mean", "std"],
        "mutation_calls": "mean",
        "mutation_failures": "mean",
        "typed_mutation_ratio": "mean",
        "protocol_gate_completion": "mean",
        "format_errors": "mean",
        "reached_edit": "mean",
        "reached_validate": "mean",
        "reached_submit": "mean",
    }
    group_summary = df.groupby("group").agg(aggregations).round(3)

    print("=" * 80)
    print("Ablation experiment summary")
    print("=" * 80)
    print(group_summary)
    print("\nVerified success rates:")
    success_rates = df.groupby("group")["verified_success"].mean() * 100
    for group, rate in success_rates.items():
        print(f"  Group {group} ({GROUP_NAMES.get(group, 'Unknown')}): {rate:.1f}%")

    if 1 in success_rates.index:
        baseline_rate = float(success_rates.loc[1])
        print("\nAbsolute change from Group 1:")
        for group, rate in success_rates.items():
            if group != 1:
                print(f"  Group {group}: {float(rate) - baseline_rate:+.1f} percentage points")

    print("\nMean total token usage:")
    for group, tokens in df.groupby("group")["total_tokens"].mean().items():
        print(f"  Group {group}: {tokens:.0f}")

    detail_file = output_path / f"ablation_results_{timestamp}.csv"
    summary_file = output_path / f"ablation_summary_{timestamp}.csv"
    df.to_csv(detail_file, index=False, encoding="utf-8-sig")
    group_summary.to_csv(summary_file, encoding="utf-8-sig")
    print(f"\nDetailed results: {detail_file}")
    print(f"Summary results:  {summary_file}")
    return detail_file, summary_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect ablation experiment artifacts")
    parser.add_argument(
        "--artifact-root",
        default="artifacts/baselines/state-event-v1",
        help="Directory containing ablation-group* run directories",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="Directory in which CSV files are written",
    )
    parser.add_argument(
        "--expected-runs",
        type=int,
        default=0,
        help="Fail if the collected run count differs; zero disables the check",
    )
    args = parser.parse_args()

    df = collect_ablation_results(args.artifact_root)
    print(f"Collected runs: {len(df)}")
    if args.expected_runs and len(df) != args.expected_runs:
        raise SystemExit(f"Expected {args.expected_runs} runs, got {len(df)}")
    if df.empty:
        raise SystemExit("No ablation results found")
    analyze_ablation_results(df, args.output_dir)


if __name__ == "__main__":
    main()
