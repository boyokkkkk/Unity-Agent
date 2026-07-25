"""Evaluate externally generated prediction patches in batch.

The single-instance evaluator is intentionally small: it applies one patch to
one benchmark instance and runs the hidden Unity tests. This module is the
leaderboard-oriented wrapper for agents outside this repository. Participants
submit JSONL rows containing patch attempts; we materialize each attempt as a
patch file, call the normal evaluator, and compute pass@k-style reports.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from . import paths
from .dataset import Instance, get_instance, load_instances
from .evaluator import read_patch_apply_status
from .passk import (
    files_modified_in_patch,
    record_detail,
    summarize,
    summarize_details,
)
from .unity_runner import ensure_results_xml, xml_says_passed


@dataclass(frozen=True)
class PredictionRecord:
    instance_id: str
    run_id: int
    model_patch: str
    agent: str | None
    model: str | None
    temperature: str | None
    line_no: int


@dataclass(frozen=True)
class PredictionMetadata:
    agent: str
    model: str
    temperature: str | None


def public_set_name(instance: Instance | str) -> str:
    """Map the dataset's internal set labels to public leaderboard folders."""
    benchmark_set = instance if isinstance(instance, str) else instance.benchmark_set
    return "golden" if benchmark_set == "golden" else "candidates"


def select_instances(
    *,
    benchmark_set: str | None = None,
    instance_ids: Iterable[str] | None = None,
) -> tuple[str, list[Instance]]:
    """Return the public set name and instances selected for one experiment.

    ``golden`` is the curated set. ``candidates`` and ``core`` are aliases for
    the non-golden pool because older dataset metadata uses ``core`` internally
    while the leaderboard UI calls that pool ``candidates``.
    """
    if instance_ids:
        ids = [instance_id.strip() for instance_id in instance_ids if instance_id.strip()]
        duplicates = sorted({instance_id for instance_id in ids if ids.count(instance_id) > 1})
        if duplicates:
            raise ValueError(f"Duplicate instance id(s): {', '.join(duplicates)}")
        instances = [get_instance(instance_id) for instance_id in ids]
        selected_sets = {public_set_name(instance) for instance in instances}
        if len(selected_sets) != 1:
            summary = ", ".join(sorted(selected_sets))
            raise ValueError(f"Cannot mix public benchmark sets in one prediction run: {summary}")
        return next(iter(selected_sets)), instances

    if not benchmark_set:
        raise ValueError("Use --set golden/candidates or --instances to choose what to evaluate.")

    normalized = benchmark_set.strip().lower()
    if normalized not in {"golden", "candidates", "candidate", "core"}:
        raise ValueError("Unknown benchmark set. Use golden, candidates, or core.")

    all_instances = load_instances()
    if normalized == "golden":
        return "golden", [instance for instance in all_instances if instance.benchmark_set == "golden"]
    return "candidates", [instance for instance in all_instances if instance.benchmark_set != "golden"]


def experiment_id(agent: str, model: str, temperature: str | None) -> str:
    raw = f"{agent}_{model}"
    if temperature not in (None, ""):
        raw += f"_t{temperature}"
    return sanitize_experiment_id(raw)


def sanitize_experiment_id(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    clean = re.sub(r"-{2,}", "-", clean).strip("-._")
    return clean or "predictions"


def _optional_string(obj: dict, key: str, line_no: int, errors: list[str]) -> str | None:
    raw = obj.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        errors.append(f"line {line_no}: {key} must be a string")
        return None
    value = raw.strip()
    if not value:
        errors.append(f"line {line_no}: {key} must not be empty when provided")
        return None
    return value


def _optional_temperature(obj: dict, line_no: int, errors: list[str]) -> str | None:
    raw = obj.get("temperature")
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        errors.append(f"line {line_no}: temperature must be a string or number")
        return None
    value = str(raw).strip()
    if not value:
        errors.append(f"line {line_no}: temperature must not be empty when provided")
        return None
    return value


def load_predictions(predictions_file: Path) -> list[PredictionRecord]:
    if not predictions_file.exists():
        raise FileNotFoundError(f"Predictions file not found: {predictions_file}")

    records: list[PredictionRecord] = []
    errors: list[str] = []
    text = predictions_file.read_text(encoding="utf-8-sig")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON ({exc.msg})")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {line_no}: expected a JSON object")
            continue

        instance_id = obj.get("instance_id")
        run_id = obj.get("run_id")
        model_patch = obj.get("model_patch")
        agent = _optional_string(obj, "agent", line_no, errors)
        model = _optional_string(obj, "model", line_no, errors)
        temperature = _optional_temperature(obj, line_no, errors)
        if not isinstance(instance_id, str) or not instance_id.strip():
            errors.append(f"line {line_no}: instance_id must be a non-empty string")
            continue
        if isinstance(run_id, bool):
            errors.append(f"line {line_no}: run_id must be an integer")
            continue
        if isinstance(run_id, int):
            run_id_int = run_id
        elif isinstance(run_id, str) and run_id.strip().isdigit():
            run_id_int = int(run_id.strip())
        else:
            errors.append(f"line {line_no}: run_id must be an integer")
            continue
        if not isinstance(model_patch, str):
            errors.append(f"line {line_no}: model_patch must be a string")
            continue

        records.append(
            PredictionRecord(
                instance_id=instance_id.strip(),
                run_id=run_id_int,
                model_patch=model_patch,
                agent=agent,
                model=model,
                temperature=temperature,
                line_no=line_no,
            )
        )

    if errors:
        raise ValueError(_format_errors("Invalid predictions file", errors))
    if not records:
        raise ValueError(f"No prediction rows found in {predictions_file}")
    return records


def resolve_metadata(
    records: list[PredictionRecord],
    *,
    agent_override: str | None = None,
    model_override: str | None = None,
    temperature_override: str | None = None,
    require_jsonl_metadata: bool = True,
) -> PredictionMetadata:
    """Infer run metadata from JSONL rows and reject mixed submissions.

    Agent and model identify the leaderboard configuration and are required.
    Temperature is optional because some model and agent APIs do not expose it.
    Optional metadata must be either present on every row or omitted everywhere.
    """

    def clean_override(value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    overrides = {
        "agent": clean_override(agent_override),
        "model": clean_override(model_override),
        "temperature": clean_override(temperature_override),
    }
    accessors = {
        "agent": lambda record: record.agent,
        "model": lambda record: record.model,
        "temperature": lambda record: record.temperature,
    }

    required_fields = {"agent", "model"}
    errors: list[str] = []
    resolved: dict[str, str | None] = {}
    for field, accessor in accessors.items():
        values_by_line = [
            (record.line_no, accessor(record))
            for record in records
            if accessor(record) is not None
        ]
        distinct_values = sorted({value for _, value in values_by_line if value is not None})
        missing_lines = [
            str(record.line_no)
            for record in records
            if accessor(record) is None
        ]

        if field in required_fields and require_jsonl_metadata and missing_lines:
            errors.append(
                f"{field} is missing from JSONL row(s): {', '.join(missing_lines[:20])}"
                + ("" if len(missing_lines) <= 20 else f", ... ({len(missing_lines)} total)")
            )
        if field not in required_fields and values_by_line and missing_lines:
            errors.append(
                f"{field} must be present on every JSONL row or omitted from every row "
                f"(missing on row(s): {', '.join(missing_lines[:20])}"
                + ("" if len(missing_lines) <= 20 else f", ... ({len(missing_lines)} total)")
                + ")"
            )
        if len(distinct_values) > 1:
            errors.append(
                f"{field} must be consistent across the JSONL submission "
                f"(found: {', '.join(distinct_values)})"
            )

        override = overrides[field]
        if override and distinct_values and distinct_values[0] != override:
            errors.append(
                f"--{field}={override} does not match JSONL {field}={distinct_values[0]}"
            )

        value = distinct_values[0] if distinct_values else override
        if field in required_fields and not value:
            errors.append(
                f"{field} is required. Put it in every JSONL row"
                + ("." if require_jsonl_metadata else " or pass the matching CLI override.")
            )
        else:
            resolved[field] = value

    if errors:
        raise ValueError(_format_errors("Invalid prediction metadata", errors))
    return PredictionMetadata(
        agent=str(resolved["agent"]),
        model=str(resolved["model"]),
        temperature=resolved["temperature"],
    )


def group_predictions(
    records: list[PredictionRecord],
    instances: list[Instance],
    *,
    k: int,
    allow_incomplete: bool = False,
) -> dict[str, dict[int, PredictionRecord]]:
    if k <= 0:
        raise ValueError("k must be positive.")

    expected_ids = {instance.instance_id for instance in instances}
    grouped: dict[str, dict[int, PredictionRecord]] = {instance.instance_id: {} for instance in instances}
    errors: list[str] = []

    for record in records:
        if record.instance_id not in expected_ids:
            errors.append(
                f"line {record.line_no}: unexpected instance_id '{record.instance_id}' "
                "for the selected benchmark set"
            )
            continue
        if not 1 <= record.run_id <= k:
            errors.append(f"line {record.line_no}: run_id must be in 1..{k}")
            continue
        existing = grouped[record.instance_id].get(record.run_id)
        if existing is not None:
            errors.append(
                f"line {record.line_no}: duplicate prediction for "
                f"{record.instance_id} run_id={record.run_id} "
                f"(first seen on line {existing.line_no})"
            )
            continue
        grouped[record.instance_id][record.run_id] = record

    for instance in instances:
        run_ids = sorted(grouped[instance.instance_id])
        if not run_ids:
            if not allow_incomplete:
                errors.append(f"{instance.instance_id}: missing all {k} prediction rows")
            continue

        expected_run_ids = list(range(1, k + 1))
        if not allow_incomplete and run_ids != expected_run_ids:
            missing = [str(run_id) for run_id in expected_run_ids if run_id not in grouped[instance.instance_id]]
            errors.append(f"{instance.instance_id}: missing run_id(s) {', '.join(missing)}")
        if allow_incomplete:
            contiguous = list(range(1, len(run_ids) + 1))
            if run_ids != contiguous:
                errors.append(
                    f"{instance.instance_id}: incomplete runs must be contiguous from 1 "
                    f"(got {', '.join(map(str, run_ids))})"
                )

    if errors:
        raise ValueError(_format_errors("Prediction rows do not match the selected benchmark set", errors))
    return grouped


def _format_errors(title: str, errors: list[str], limit: int = 20) -> str:
    shown = errors[:limit]
    suffix = "" if len(errors) <= limit else f"\n... and {len(errors) - limit} more error(s)"
    return title + ":\n" + "\n".join(f"- {error}" for error in shown) + suffix


def _save_json(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")


def _refresh_aggregate(report: dict, k_report: list[int]) -> None:
    instances = report.get("instances", {})
    if not instances:
        report["aggregate"] = {"n_instances": 0}
        return
    aggregate: dict = {"n_instances": len(instances)}
    for k_value in k_report:
        key = f"pass@{k_value}"
        values = [
            instance_result.get(key)
            for instance_result in instances.values()
            if isinstance(instance_result.get(key), (int, float))
        ]
        if values:
            aggregate[key] = round(sum(values) / len(values), 6)
    report["aggregate"] = aggregate


def _run_cmd(cmd: list[str], log_path: Path, timeout: int | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("CMD:", " ".join(str(part) for part in cmd), flush=True)
    with log_path.open("w", encoding="utf-8", buffering=1) as fh:
        fh.write(f"=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        fh.write("CMD: " + " ".join(str(part) for part in cmd) + "\n")
        fh.flush()
        proc = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
        )
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            msg = "\n[PREDICTIONS] TIMEOUT\n"
            print(msg, flush=True)
            fh.write(msg)
            return 124


def _write_synthetic_failure(
    xml_path: Path,
    log_path: Path,
    label: str,
    message: str,
    *,
    extra_log_path: Path | None = None,
) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    for path in (log_path, extra_log_path):
        if path is not None and not path.exists():
            path.write_text(message + "\n", encoding="utf-8")
    ensure_results_xml(xml_path, label, log_path, extra_msg=message)


def _annotate_detail(details: dict, instance_id: str, run_id: int, extra: dict) -> None:
    block = details.get("instances", {}).get(instance_id)
    if not block:
        return
    for run in block.get("runs", []):
        if run.get("run_idx") == run_id:
            run.update(extra)
            return


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _evaluation_backend_args(*, local: bool, forced_backend: str | None, fresh: bool) -> list[str]:
    args: list[str] = []
    if local:
        args.append("--local")
    elif forced_backend:
        args.extend(["--backend", forced_backend])
    if fresh:
        args.append("--fresh")
    return args


def evaluate_predictions(
    *,
    predictions_file: Path,
    agent: str | None = None,
    model: str | None = None,
    temperature: str | None = None,
    benchmark_set: str | None = None,
    instance_ids: list[str] | None = None,
    k: int = 10,
    runs_root: Path | None = None,
    experiment: str | None = None,
    allow_incomplete: bool = False,
    skip_existing: bool = False,
    eval_timeout: int = 2700,
    local: bool = False,
    forced_backend: str | None = None,
    fresh: bool = False,
    verified: bool = False,
    logs_url: str | None = None,
) -> int:
    if benchmark_set and instance_ids:
        raise ValueError("Use either --set for a public submission or --instances for a manual run, not both.")
    if allow_incomplete and not instance_ids:
        raise ValueError("--allow-incomplete is only allowed with --instances for manual smoke tests.")
    if benchmark_set and k != 10:
        raise ValueError("Public benchmark set submissions require --k 10.")

    public_set, instances = select_instances(benchmark_set=benchmark_set, instance_ids=instance_ids)
    records = load_predictions(predictions_file)
    grouped = group_predictions(records, instances, k=k, allow_incomplete=allow_incomplete)
    metadata = resolve_metadata(
        records,
        agent_override=agent,
        model_override=model,
        temperature_override=temperature,
        require_jsonl_metadata=not allow_incomplete,
    )

    experiment = (
        sanitize_experiment_id(experiment)
        if experiment
        else experiment_id(metadata.agent, metadata.model, metadata.temperature)
    )
    if runs_root is None:
        runs_root = paths.runs_root() / public_set / "predictions" / experiment
    else:
        runs_root = Path(runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)

    generated_at = datetime.now(timezone.utc).isoformat()
    k_report = list(range(1, k + 1))
    report_path = runs_root / "pass_at_k_report.json"
    details_path = runs_root / "pass_at_k_details.json"
    batch_log = runs_root / "evaluate_predictions.log"

    common_metadata = {
        "schema_version": 1,
        "generated_at": generated_at,
        "source": "predictions",
        "agent": metadata.agent,
        "model": metadata.model,
        "temperature": metadata.temperature,
        "benchmark_set": public_set,
        "experiment": experiment,
        "k": k,
        "runs_root": str(runs_root),
        "predictions_file": str(predictions_file),
        "verified": bool(verified),
        "logs": True,
        "logs_url": logs_url,
    }
    report: dict = {**common_metadata, "instances": {}}
    details: dict = {**common_metadata, "instances": {}}

    backend_args = _evaluation_backend_args(local=local, forced_backend=forced_backend, fresh=fresh)
    cli = [sys.executable, "-m", "swe_game_bench.cli"]
    failed_predictions = 0

    print(f"[PREDICTIONS] set={public_set}  k={k}  experiment={experiment}")
    print(f"[PREDICTIONS] instances={len(instances)}  predictions={len(records)}")
    print(f"[PREDICTIONS] runs_root={runs_root}")

    for instance in instances:
        runs_for_instance = grouped.get(instance.instance_id, {})
        if not runs_for_instance:
            continue

        print(f"\n{'=' * 60}\n[PREDICTIONS] Instance {instance.instance_id}\n{'=' * 60}")
        bits: list[bool] = []
        for run_id in sorted(runs_for_instance):
            record = runs_for_instance[run_id]
            run_dir = runs_root / instance.repo / str(instance.issue_number) / f"run{run_id}"
            run_dir.mkdir(parents=True, exist_ok=True)
            patch_path = run_dir / "candidate.patch"
            xml_path = run_dir / "candidate_results.xml"
            unity_log_path = run_dir / "candidate_unity.log"
            evaluate_log_path = run_dir / "evaluate.log"
            apply_status_path = run_dir / "candidate_apply_status.json"

            existing_result = xml_says_passed(xml_path)
            patch_matches = (
                patch_path.exists()
                and patch_path.read_text(encoding="utf-8", errors="replace") == record.model_patch
            )
            if skip_existing and patch_matches and existing_result is not None:
                print(
                    f"[PREDICTIONS] {instance.instance_id} run{run_id}: "
                    f"reusing existing result = {'PASS' if existing_result else 'FAIL'}"
                )
                reuse_message = (
                    "Reused matching existing candidate_results.xml; evaluator was not rerun."
                )
                for path in (unity_log_path, evaluate_log_path):
                    if not path.exists():
                        path.write_text(reuse_message + "\n", encoding="utf-8")
                passed = bool(existing_result)
                rc = 0 if passed else 1
                skipped = True
            else:
                xml_path.unlink(missing_ok=True)
                unity_log_path.unlink(missing_ok=True)
                evaluate_log_path.unlink(missing_ok=True)
                apply_status_path.unlink(missing_ok=True)
                patch_path.write_text(record.model_patch, encoding="utf-8")
                if not record.model_patch.strip():
                    rc = 1
                    skipped = True
                    passed = False
                    _write_synthetic_failure(
                        xml_path,
                        unity_log_path,
                        "candidate",
                        "Candidate patch is empty.",
                        extra_log_path=evaluate_log_path,
                    )
                    print(f"[PREDICTIONS] {instance.instance_id} run{run_id}: empty patch -> FAIL")
                elif not files_modified_in_patch(patch_path):
                    rc = 1
                    skipped = True
                    passed = False
                    _write_synthetic_failure(
                        xml_path,
                        unity_log_path,
                        "candidate",
                        "Candidate patch is not a parseable unified diff.",
                        extra_log_path=evaluate_log_path,
                    )
                    print(
                        f"[PREDICTIONS] {instance.instance_id} run{run_id}: "
                        "unparseable patch -> FAIL"
                    )
                else:
                    skipped = False
                    cmd = cli + [
                        "evaluate",
                        "--instance-id",
                        instance.instance_id,
                        "--patch-file",
                        str(patch_path),
                        "--label",
                        "candidate",
                        "--outdir",
                        str(run_dir),
                        *backend_args,
                    ]
                    rc = _run_cmd(cmd, evaluate_log_path, timeout=eval_timeout)
                    result = xml_says_passed(xml_path)
                    if result is None:
                        message = (
                            "Evaluator exited before writing a parseable Unity result. "
                            "The patch may have failed to apply or Unity may have failed before tests ran."
                        )
                        if evaluate_log_path.exists():
                            unity_log_path.write_text(
                                evaluate_log_path.read_text(encoding="utf-8", errors="replace"),
                                encoding="utf-8",
                            )
                        _write_synthetic_failure(xml_path, unity_log_path, "candidate", message)
                        result = False
                    passed = bool(result)
                    if rc != 0 and passed:
                        print(
                            f"[PREDICTIONS][WARN] {instance.instance_id} run{run_id}: "
                            f"evaluator rc={rc} but XML passed"
                        )

            if rc != 0 and not passed:
                failed_predictions += 1
            bits.append(passed)
            record_detail(
                details,
                instance,
                run_id,
                passed=passed,
                xml_path=xml_path,
                patch_path=patch_path,
                patch_applied=read_patch_apply_status(run_dir, "candidate"),
            )
            _annotate_detail(
                details,
                instance.instance_id,
                run_id,
                {
                    "patch_path": _relative_to(patch_path, runs_root),
                    "xml_path": _relative_to(xml_path, runs_root),
                    "unity_log_path": _relative_to(unity_log_path, runs_root),
                    "evaluate_log_path": _relative_to(evaluate_log_path, runs_root),
                    "evaluate_returncode": rc,
                    "skipped_before_evaluate": skipped,
                },
            )
            summarize_details(details)
            _save_json(details, details_path)

            report["instances"][instance.instance_id] = summarize(bits, k_report)
            _refresh_aggregate(report, k_report)
            _save_json(report, report_path)

            print(
                f"[PREDICTIONS] {instance.instance_id} run{run_id}: "
                f"{'PASS' if passed else 'FAIL'}"
            )

    summarize_details(details)
    _save_json(details, details_path)
    _refresh_aggregate(report, k_report)
    _save_json(report, report_path)

    with batch_log.open("w", encoding="utf-8") as fh:
        fh.write(
            f"Predictions: {predictions_file}\n"
            f"Experiment: {experiment}\n"
            f"Set: {public_set}\n"
            f"k: {k}\n"
            f"Report: {report_path}\n"
            f"Details: {details_path}\n"
        )

    print(f"\n[PREDICTIONS] Report written to {report_path}")
    print(f"[PREDICTIONS] Details written to {details_path}")
    if not allow_incomplete:
        expected_rows = len(instances) * k
        print(f"[PREDICTIONS] Evaluated {expected_rows} expected prediction row(s).")
    print(f"[PREDICTIONS] Failed prediction attempts: {failed_predictions}")
    print(
        "[PREDICTIONS] Next: run `swe-game-bench report` to generate "
        "leaderboard-ready reports from this result tree."
    )
    return 0
