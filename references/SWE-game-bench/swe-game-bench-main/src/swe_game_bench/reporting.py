"""Aggregate pass@k and prediction reports into leaderboard-ready files."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import paths
from .dataset import load_instances


def run_patch_applied(run: dict) -> bool:
    """Return explicit apply status, with a conservative fallback for legacy runs."""
    applied = run.get("patch_applied")
    if isinstance(applied, bool):
        return applied

    # Older detail files predate the apply-status artifact. Reaching the Unity
    # tests proves that git apply succeeded, but absence of test cases does not.
    summary = run.get("test_case_summary", {})
    return bool(run.get("passed")) or int(summary.get("total", 0)) > 0


def run_hits_any_target(run: dict, target_files: list[str]) -> bool:
    return bool(set(target_files) & set(run.get("files_modified", [])))


def run_hits_all_targets(run: dict, target_files: list[str]) -> bool:
    targets = set(target_files)
    return bool(targets) and targets <= set(run.get("files_modified", []))


def build_reports(
    *,
    runs_root: Path | None = None,
    model: str | None = None,
    temperature: str | None = None,
    benchmark_set: str | None = None,
    include_incomplete: bool = False,
) -> int:
    """Build per-configuration reports and the global leaderboard index."""
    root = runs_root if runs_root else paths.runs_root()
    reports = sorted(root.rglob("pass_at_k_report.json"))
    if not reports:
        print(f"No pass_at_k_report.json found under {root}")
        return 1

    instances = load_instances()
    instances_by_id = {instance.instance_id: instance for instance in instances}
    expected_by_set = {"candidates": [], "golden": []}
    for instance in instances:
        set_name = "golden" if instance.benchmark_set == "golden" else "candidates"
        expected_by_set[set_name].append(instance.instance_id)

    report_roots = {"passk", "predictions"}
    grouped_reports: dict[tuple[str, str], list[tuple[Path, dict]]] = {}
    for rp in reports:
        try:
            rep = json.loads(rp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        report_indexes = [i for i, part in enumerate(rp.parts) if part in report_roots]
        if not report_indexes:
            continue
        report_index = report_indexes[-1]
        if report_index == 0 or report_index + 1 >= len(rp.parts):
            continue
        set_name = rp.parts[report_index - 1]
        if set_name not in expected_by_set:
            continue
        experiment_id = rp.parts[report_index + 1]

        if model and str(rep.get("model")) != model:
            continue
        if temperature is not None and str(rep.get("temperature")) != str(temperature):
            continue
        if benchmark_set and set_name != benchmark_set:
            continue

        grouped_reports.setdefault((set_name, experiment_id), []).append((rp, rep))

    if not grouped_reports:
        filters = ", ".join(
            value
            for value in (
                f"model={model}" if model else "",
                f"temperature={temperature}" if temperature is not None else "",
                f"set={benchmark_set}" if benchmark_set else "",
            )
            if value
        )
        print(f"No pass@k reports matched the requested configuration ({filters}).")
        return 1

    def score_key_order(key: str) -> int:
        try:
            return int(key.split("@", 1)[1])
        except (IndexError, ValueError):
            return 10**9

    def write_csv(path: Path, csv_rows: list[dict], fieldnames: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_rows)

    generated_at = datetime.now(timezone.utc).isoformat()
    reports_root = root / "reports"
    leaderboard_rows = []
    leaderboard_results = []
    omitted_incomplete = 0

    for (set_name, experiment_id), experiment_reports in sorted(grouped_reports.items()):
        expected_ids = expected_by_set[set_name]
        expected_set = set(expected_ids)
        merged: dict[str, dict] = {}
        merged_details: dict[str, dict] = {}
        extra_ids: set[str] = set()
        duplicate_ids: set[str] = set()

        for report_path, report in experiment_reports:
            try:
                source = report_path.relative_to(root).as_posix()
            except ValueError:
                source = report_path.name
            for instance_id, result in report.get("instances", {}).items():
                if instance_id not in expected_set:
                    extra_ids.add(instance_id)
                    continue
                candidate = dict(result)
                candidate["source_report"] = source
                existing = merged.get(instance_id)
                if existing is not None:
                    duplicate_ids.add(instance_id)
                if existing is None or int(candidate.get("n_runs", 0)) > int(existing.get("n_runs", 0)):
                    merged[instance_id] = candidate

            details_path = report_path.with_name("pass_at_k_details.json")
            if not details_path.exists():
                continue
            try:
                details = json.loads(details_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for instance_id, detail in details.get("instances", {}).items():
                if instance_id not in expected_set:
                    continue
                existing_detail = merged_details.get(instance_id)
                if (
                    existing_detail is None
                    or len(detail.get("runs", [])) > len(existing_detail.get("runs", []))
                ):
                    merged_details[instance_id] = detail

        representative = max(
            (report for _, report in experiment_reports),
            key=lambda report: len(report.get("instances", {})),
        )
        representative_model = representative.get("model", "?")
        representative_temperature = representative.get("temperature")
        agent = representative.get("agent", "swe-agent")
        verified = bool(representative.get("verified", False))
        logs_url = representative.get("logs_url")
        logs_available = bool(representative.get("logs", bool(logs_url)))
        missing_ids = [instance_id for instance_id in expected_ids if instance_id not in merged]
        completed = len(merged)

        common_scores: set[str] | None = None
        for result in merged.values():
            result_scores = {key for key in result if key.startswith("pass@")}
            common_scores = result_scores if common_scores is None else common_scores & result_scores
        score_keys = sorted(common_scores or set(), key=score_key_order)
        aggregate_scores = {
            key: round(sum(float(result[key]) for result in merged.values()) / completed, 6)
            for key in score_keys
        } if completed else {}
        max_k = max((score_key_order(key) for key in score_keys), default=None)

        parseable_by_instance: dict[str, float] = {}
        filehit_by_instance: dict[str, float] = {}
        filehit_any_by_instance: dict[str, float] = {}
        for instance_id in expected_ids:
            detail = merged_details.get(instance_id, {})
            target_files = instances_by_id[instance_id].target_files
            runs = sorted(
                detail.get("runs", []),
                key=lambda run: int(run.get("run_idx", 0)),
            )[:10]
            # Canonical parsability requires a non-empty diff with at least one
            # parsed file path that also applied cleanly. Canonical file hit
            # requires one attempt to cover every oracle target file.
            parseable_by_instance[instance_id] = float(
                any(
                    int(run.get("files_modified_count", 0)) > 0
                    and run_patch_applied(run)
                    for run in runs
                )
            )
            filehit_by_instance[instance_id] = float(
                any(run_hits_all_targets(run, target_files) for run in runs)
            )
            filehit_any_by_instance[instance_id] = float(
                any(run_hits_any_target(run, target_files) for run in runs)
            )

        expected_count = len(expected_ids)
        parseable_at_10 = round(
            sum(parseable_by_instance.values()) / expected_count, 6
        )
        filehit_at_10 = round(
            sum(filehit_by_instance.values()) / expected_count, 6
        )
        filehit_any_at_10 = round(
            sum(filehit_any_by_instance.values()) / expected_count, 6
        )
        pass_at_10 = float(aggregate_scores.get("pass@10", 0.0))
        composite_score = round(parseable_at_10 * filehit_at_10 * pass_at_10, 6)
        aggregate_scores.update(
            {
                "parseable@10": parseable_at_10,
                "filehit@10": filehit_at_10,
                "score": composite_score,
            }
        )

        instance_rows = []
        instance_results = []
        for instance_id in expected_ids:
            result = merged.get(instance_id)
            if result is None:
                instance_rows.append({"instance_id": instance_id, "status": "missing"})
                instance_results.append({"instance_id": instance_id, "status": "missing"})
                continue
            scores = {
                **{key: result[key] for key in score_keys},
                "parseable@10": parseable_by_instance[instance_id],
                "filehit@10": filehit_by_instance[instance_id],
            }
            instance_rows.append(
                {
                    "instance_id": instance_id,
                    "status": "complete",
                    "n_runs": result.get("n_runs"),
                    "n_passed": result.get("n_passed"),
                    "first_pass_run": result.get("first_pass_run"),
                    **scores,
                    "source_report": result.get("source_report"),
                }
            )
            instance_results.append(
                {
                    "instance_id": instance_id,
                    "status": "complete",
                    "n_runs": result.get("n_runs"),
                    "n_passed": result.get("n_passed"),
                    "first_pass_run": result.get("first_pass_run"),
                    "bits": result.get("bits", []),
                    "scores": scores,
                    "diagnostics": {
                        "filehit_any@10": filehit_any_by_instance[instance_id],
                    },
                    "source_report": result.get("source_report"),
                }
            )

        config_dir = reports_root / set_name / experiment_id
        instance_header = [
            "instance_id",
            "status",
            "n_runs",
            "n_passed",
            "first_pass_run",
            "parseable@10",
            "filehit@10",
            *score_keys,
            "source_report",
        ]
        write_csv(config_dir / "leaderboard.csv", instance_rows, instance_header)
        (config_dir / "leaderboard.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "generated_at": generated_at,
                    "configuration": {
                        "id": experiment_id,
                        "agent": agent,
                        "model": representative_model,
                        "temperature": representative_temperature,
                        "benchmark_set": set_name,
                        "k": max_k,
                        "verified": verified,
                        "logs": logs_available,
                        "logs_url": logs_url,
                    },
                    "coverage": {
                        "expected": len(expected_ids),
                        "completed": completed,
                        "complete": completed == len(expected_ids),
                        "missing_instance_ids": missing_ids,
                        "excluded_instance_ids": sorted(extra_ids),
                        "deduplicated_instance_ids": sorted(duplicate_ids),
                    },
                    "aggregate": aggregate_scores,
                    "diagnostics": {
                        "filehit_any@10": filehit_any_at_10,
                    },
                    "instances": instance_results,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        config_report = (
            config_dir.relative_to(root).as_posix() + "/leaderboard.json"
        )
        leaderboard_row = {
            "agent": agent,
            "model": representative_model,
            "temp": representative_temperature,
            "benchmark_set": set_name,
            "experiment": experiment_id,
            "k": max_k,
            "completed": completed,
            "expected": len(expected_ids),
            "complete": completed == len(expected_ids),
            **aggregate_scores,
            "verified": verified,
            "logs": logs_available,
            "logs_url": logs_url or "",
            "report": config_report,
        }
        leaderboard_result = {
            "agent": agent,
            "model": representative_model,
            "temperature": representative_temperature,
            "benchmark_set": set_name,
            "experiment": experiment_id,
            "k": max_k,
            "coverage": {
                "expected": len(expected_ids),
                "completed": completed,
                "complete": completed == len(expected_ids),
            },
            "scores": aggregate_scores,
            "verified": verified,
            "logs": logs_available,
            "logs_url": logs_url,
            "report": config_report,
        }
        if leaderboard_row["complete"] or include_incomplete:
            leaderboard_rows.append(leaderboard_row)
            leaderboard_results.append(leaderboard_result)
        else:
            omitted_incomplete += 1

    pass_score_keys = sorted(
        {
            key
            for row in leaderboard_rows
            for key in row
            if key.startswith("pass@")
        },
        key=score_key_order,
    )
    leaderboard_header = [
        "agent",
        "model",
        "temp",
        "benchmark_set",
        "experiment",
        "k",
        "completed",
        "expected",
        "complete",
        "parseable@10",
        "filehit@10",
        *pass_score_keys,
        "score",
        "verified",
        "logs",
        "logs_url",
        "report",
    ]
    print("  ".join(f"{header:<14}" for header in leaderboard_header))
    for row in leaderboard_rows:
        print("  ".join(f"{str(row.get(header, '')):<14}" for header in leaderboard_header))

    filtered = bool(model or temperature is not None or benchmark_set)
    out_csv = root / "leaderboard.csv"
    out_json = root / "leaderboard.json"
    if filtered and out_json.exists():
        try:
            existing_results = json.loads(
                out_json.read_text(encoding="utf-8")
            ).get("results", [])
        except (OSError, json.JSONDecodeError):
            existing_results = []
        updated_keys = {
            (result["benchmark_set"], result["experiment"])
            for result in leaderboard_results
        }
        leaderboard_results = [
            result
            for result in existing_results
            if (result.get("benchmark_set"), result.get("experiment")) not in updated_keys
        ] + leaderboard_results
        if not include_incomplete:
            leaderboard_results = [
                result
                for result in leaderboard_results
                if bool(result.get("coverage", {}).get("complete"))
            ]
        leaderboard_results.sort(
            key=lambda result: (
                str(result.get("benchmark_set", "")),
                str(result.get("experiment", "")),
            )
        )
        leaderboard_rows = [
            {
                "agent": result.get("agent"),
                "model": result.get("model"),
                "temp": result.get("temperature"),
                "benchmark_set": result.get("benchmark_set"),
                "experiment": result.get("experiment"),
                "k": result.get("k"),
                "completed": result.get("coverage", {}).get("completed"),
                "expected": result.get("coverage", {}).get("expected"),
                "complete": result.get("coverage", {}).get("complete"),
                **result.get("scores", {}),
                "verified": result.get("verified", False),
                "logs": result.get("logs", False),
                "logs_url": result.get("logs_url") or "",
                "report": result.get("report"),
            }
            for result in leaderboard_results
        ]
        pass_score_keys = sorted(
            {
                key
                for row in leaderboard_rows
                for key in row
                if key.startswith("pass@")
            },
            key=score_key_order,
        )
        leaderboard_header = [
            "agent", "model", "temp", "benchmark_set", "experiment", "k",
            "completed", "expected", "complete", "parseable@10", "filehit@10",
            *pass_score_keys, "score", "verified", "logs", "logs_url", "report",
        ]

    for result in leaderboard_results:
        result.get("scores", {}).pop("filehit_any@10", None)

    write_csv(out_csv, leaderboard_rows, leaderboard_header)
    out_json.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "generated_at": generated_at,
                "results": leaderboard_results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\n{'Updated' if filtered else 'Wrote'} {out_csv}")
    print(f"{'Updated' if filtered else 'Wrote'} {out_json}")
    print(f"Wrote {len(grouped_reports)} configuration report(s) under {reports_root}")
    if omitted_incomplete and not include_incomplete:
        print(
            f"Omitted {omitted_incomplete} incomplete experiment(s) from the global leaderboard. "
            "Use --include-incomplete to publish them for diagnostics."
        )
    return 0
