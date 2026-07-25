"""pass@k batch runner: k independent generate+evaluate runs per instance.

For each (instance, run index):
  1. swe-game-bench generate -> runs/<set>/passk/<experiment>/<instance>/run<N>/swe_agent.patch
  2. swe-game-bench evaluate -> runs/<set>/passk/<experiment>/<instance>/run<N>/swe_agent_results.xml
  3. Parse the NUnit XML to decide pass/fail.

Both steps run as subprocesses so per-run timeouts can kill a hung Unity or
agent without taking the batch down. Reports:
  pass_at_k_report.json   pass@k per instance + aggregate (unbiased estimator)
  pass_at_k_details.json  per-test-case results + file-level localization
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import paths
from .dataset import Instance, get_instance, get_repo, load_instances
from .unity_runner import parse_test_cases, xml_says_passed


# --------------------------------------------------------------------------
# pass@k estimator
# --------------------------------------------------------------------------

def pass_at_k_unbiased(n: int, c: int, k: int) -> float:
    """Codex pass@k unbiased estimator."""
    if n <= 0 or k <= 0:
        return float("nan")
    if n - c < k:
        return 1.0
    if k > n:
        return float("nan")
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k))


def summarize(bits: list[bool], k_list: list[int]) -> dict:
    n = len(bits)
    c = sum(1 for b in bits if b)
    first_pass = next((i + 1 for i, b in enumerate(bits) if b), None)
    out: dict = {
        "n_runs": n,
        "n_passed": c,
        "first_pass_run": first_pass,
        "bits": [int(b) for b in bits],
    }
    for k in k_list:
        if k <= n:
            out[f"pass@{k}"] = round(pass_at_k_unbiased(n, c, k), 6)
    return out


# --------------------------------------------------------------------------
# details collector (per test-case results + file-level localization)
# --------------------------------------------------------------------------

def files_modified_in_patch(patch_path: Path) -> list[str]:
    if not patch_path.exists() or patch_path.stat().st_size == 0:
        return []
    try:
        text = patch_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    files: set[str] = set()
    for m in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", text, re.MULTILINE):
        files.add(m.group(2))
    if not files:
        for m in re.finditer(r"^\+\+\+ b/(.+?)$", text, re.MULTILINE):
            files.add(m.group(1))
    return sorted(files)


def record_detail(
    details: dict,
    instance: Instance,
    run_idx: int,
    *,
    passed: bool | None,
    xml_path: Path,
    patch_path: Path,
    patch_applied: bool | None = None,
) -> None:
    block = details.setdefault("instances", {}).setdefault(
        instance.instance_id, {"target_files": instance.target_files, "runs": []}
    )
    block["target_files"] = instance.target_files
    cases = parse_test_cases(xml_path)
    modified = files_modified_in_patch(patch_path)
    target_files = set(instance.target_files)
    modified_files = set(modified)
    hit_any = bool(target_files & modified_files)
    hit_all = bool(target_files) and target_files <= modified_files
    entry = {
        "run_idx": run_idx,
        "passed": bool(passed) if passed is not None else None,
        "patch_applied": patch_applied,
        "files_modified": modified,
        "files_modified_count": len(modified),
        "hit_target": hit_all,
        "hit_target_any": hit_any,
        "hit_target_all": hit_all,
        "test_case_summary": {
            "total": len(cases),
            "passed": sum(1 for c in cases if c.get("result") == "Passed"),
            "failed": sum(1 for c in cases if c.get("result") == "Failed"),
        },
        "test_cases": cases,
    }
    runs = block["runs"]
    for i, existing in enumerate(runs):
        if existing.get("run_idx") == run_idx:
            runs[i] = entry
            break
    else:
        runs.append(entry)
    runs.sort(key=lambda r: r.get("run_idx", 0))


def summarize_details(details: dict) -> None:
    instances = details.get("instances", {})
    if not instances:
        return
    total_runs = total_hits = total_hits_any = 0
    for block in instances.values():
        runs = block.get("runs", [])
        target_files = set(block.get("target_files", []))
        for run in runs:
            modified_files = set(run.get("files_modified", []))
            hit_any = bool(target_files & modified_files)
            hit_all = bool(target_files) and target_files <= modified_files
            run["hit_target"] = hit_all
            run["hit_target_any"] = hit_any
            run["hit_target_all"] = hit_all
        n = len(runs)
        h = sum(1 for r in runs if r.get("hit_target"))
        h_any = sum(1 for r in runs if r.get("hit_target_any"))
        passed = sum(1 for r in runs if r.get("passed"))
        block["aggregate"] = {
            "n_runs": n,
            "n_passed": passed,
            "hit_target_count": h,
            "hit_target_rate": round(h / n, 6) if n else 0.0,
            "hit_target_any_count": h_any,
            "hit_target_any_rate": round(h_any / n, 6) if n else 0.0,
        }
        total_runs += n
        total_hits += h
        total_hits_any += h_any
    details["aggregate"] = {
        "n_instances": len(instances),
        "n_runs_total": total_runs,
        "hit_target_count": total_hits,
        "hit_target_rate": round(total_hits / total_runs, 6) if total_runs else 0.0,
        "hit_target_any_count": total_hits_any,
        "hit_target_any_rate": (
            round(total_hits_any / total_runs, 6) if total_runs else 0.0
        ),
    }


# --------------------------------------------------------------------------
# batch runner
# --------------------------------------------------------------------------

def _run_cmd(cmd: list[str], log_path: Path, timeout: int | None = None) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    print("CMD:", " ".join(str(x) for x in cmd), flush=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        fh.write("CMD: " + " ".join(str(x) for x in cmd) + "\n")
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", errors="replace")
            out += "\n[BATCH] TIMEOUT\n"
            print(out, flush=True)
            fh.write(out)
            return 124
        fh.write(proc.stdout)
    print(proc.stdout, flush=True)
    return proc.returncode


def _host_has_unity() -> bool:
    return Path(os.getenv("UNITY", "/opt/unity/Editor/Unity")).exists()


def _cleanup_workdir(path: Path, log_path: Path) -> None:
    """Reset the shared checkout between runs; fall back to deleting it."""
    if not path.exists():
        return
    print(f"[BATCH] Cleaning workdir: {path}", flush=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[BATCH] Cleaning workdir: {path}\n")
        if path.is_dir() and (path / ".git").exists():
            repo_clean = True
            for cmd in (["git", "reset", "--hard", "HEAD"], ["git", "clean", "-fdx"]):
                fh.write("CMD: " + " ".join(cmd) + "\n")
                proc = subprocess.run(
                    cmd, cwd=path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, errors="replace",
                )
                fh.write(proc.stdout)
                if proc.returncode != 0:
                    repo_clean = False
                    fh.write("[BATCH] Git cleanup failed. Falling back to deleting workdir.\n")
                    break
            if repo_clean:
                return
    if path.is_file():
        path.unlink()
    else:
        shutil.rmtree(path, ignore_errors=True)


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return dict(default)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)
    return loaded if isinstance(loaded, dict) else dict(default)


def _save_json(obj: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2), encoding="utf-8")


def _refresh_aggregate(report: dict, k_report: list[int]) -> None:
    instances = report.get("instances", {})
    if not instances:
        return
    aggregate: dict = {"n_instances": len(instances)}
    for k in k_report:
        key = f"pass@{k}"
        values = [
            instances[i].get(key)
            for i in instances
            if isinstance(instances[i].get(key), (int, float))
        ]
        if values:
            aggregate[key] = round(sum(values) / len(values), 6)
    report["aggregate"] = aggregate


def run_pass_at_k(
    instance_ids: list[str] | None,
    k: int,
    model: str,
    runs_root: Path | None = None,
    *,
    benchmark_set: str | None = None,
    start_run: int = 1,
    skip_existing: bool = False,
    stop_on_first_pass: bool = False,
    gen_timeout: int = 1800,
    eval_timeout: int = 2700,
    cleanup_workdir: bool = True,
) -> int:
    instances = (
        [get_instance(i) for i in instance_ids]
        if instance_ids
        else load_instances()
    )
    if benchmark_set:
        instances = [instance for instance in instances if instance.benchmark_set == benchmark_set]
    if not instances:
        print("[ERROR] No instances to run.")
        return 1
    selected_sets = {instance.benchmark_set for instance in instances}
    if len(selected_sets) > 1:
        counts = {
            set_name: sum(instance.benchmark_set == set_name for instance in instances)
            for set_name in sorted(selected_sets)
        }
        summary = ", ".join(f"{name}={count}" for name, count in counts.items())
        print(f"[ERROR] Cannot mix benchmark sets in one pass@k experiment ({summary}).")
        print(
            "[hint] Use --set golden or --set core, or pass --instances containing "
            "instances from only one set."
        )
        return 2
    selected_set = next(iter(selected_sets))

    from .agents.sweagent import DEFAULT_TEMPERATURE

    temperature = DEFAULT_TEMPERATURE
    if runs_root:
        runs_root = Path(runs_root)
    else:
        # Scope results by experiment so changing model/temperature in .env
        # starts a new result tree instead of overwriting the previous one.
        experiment = f"{model}_t{temperature}".replace("/", "-").replace(":", "-")
        run_set = "golden" if selected_set == "golden" else "candidates"
        runs_root = paths.runs_root() / run_set / "passk" / experiment
    runs_root.mkdir(parents=True, exist_ok=True)
    k_report = list(range(1, k + 1))

    print(f"[BATCH] Instances: {[i.instance_id for i in instances]}")
    print(f"[BATCH] k={k}  model={model}  temperature={temperature}  runs_root={runs_root}")

    report_path = runs_root / "pass_at_k_report.json"
    details_path = runs_root / "pass_at_k_details.json"
    batch_log = runs_root / "pass_at_k_batch.log"

    report = _load_json(report_path, {"instances": {}})
    report.update({"model": model, "temperature": temperature, "k": k, "runs_root": str(runs_root)})
    report.setdefault("instances", {})

    details = _load_json(details_path, {"instances": {}})
    details.update({"model": model, "temperature": temperature, "k": k, "runs_root": str(runs_root)})
    details.setdefault("instances", {})

    def _record(inst: Instance, run_idx: int, xml: Path, patch: Path, passed: bool | None):
        from .evaluator import read_patch_apply_status

        patch_applied = read_patch_apply_status(xml.parent, "swe_agent")
        record_detail(
            details,
            inst,
            run_idx,
            passed=passed,
            xml_path=xml,
            patch_path=patch,
            patch_applied=patch_applied,
        )
        _save_json(details, details_path)

    cli = [sys.executable, "-m", "swe_game_bench.cli"]

    for inst in instances:
        print(f"\n{'=' * 60}\n[BATCH] Instance {inst.instance_id}\n{'=' * 60}")
        inst_dir = runs_root / inst.repo / str(inst.issue_number)
        inst_dir.mkdir(parents=True, exist_ok=True)
        bits: list[bool] = []
        workdir = get_repo(inst.repo).resolved_workdir()

        for run_idx in range(1, k + 1):
            run_dir = inst_dir / f"run{run_idx}"
            patch_path = run_dir / "swe_agent.patch"
            xml_path = run_dir / "swe_agent_results.xml"

            if run_idx < start_run:
                existing = xml_says_passed(xml_path)
                if existing is not None:
                    bits.append(bool(existing))
                    _record(inst, run_idx, xml_path, patch_path, bool(existing))
                continue

            if skip_existing and xml_path.exists():
                existing = xml_says_passed(xml_path)
                if existing is not None:
                    print(f"[BATCH] {inst.instance_id} run{run_idx}: reusing existing result = "
                          f"{'PASS' if existing else 'FAIL'}")
                    bits.append(bool(existing))
                    _record(inst, run_idx, xml_path, patch_path, bool(existing))
                    if existing and stop_on_first_pass:
                        break
                    continue

            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "swe_agent_apply_status.json").unlink(missing_ok=True)
            if cleanup_workdir and _host_has_unity():
                _cleanup_workdir(workdir, batch_log)

            # Step 1: generate patch
            gen_rc = _run_cmd(
                cli + ["generate", "--instance-id", inst.instance_id,
                       "--model", model, "--outdir", str(run_dir)],
                batch_log, timeout=gen_timeout,
            )
            if gen_rc != 0 or not patch_path.exists() or patch_path.stat().st_size == 0:
                print(f"[BATCH] {inst.instance_id} run{run_idx}: generation failed (rc={gen_rc}). "
                      f"Recording as FAIL.")
                bits.append(False)
                _record(inst, run_idx, xml_path, patch_path, False)
                report["instances"][inst.instance_id] = summarize(bits, k_report)
                _save_json(report, report_path)
                continue

            # Step 2: evaluate patch
            _run_cmd(
                cli + ["evaluate", "--instance-id", inst.instance_id,
                       "--patch-file", str(patch_path),
                       "--label", "swe_agent", "--outdir", str(run_dir)],
                batch_log, timeout=eval_timeout,
            )

            result = xml_says_passed(xml_path)
            if result is None:
                print(f"[BATCH] {inst.instance_id} run{run_idx}: no parseable XML. Recording as FAIL.")
                bits.append(False)
                _record(inst, run_idx, xml_path, patch_path, False)
            else:
                bits.append(bool(result))
                _record(inst, run_idx, xml_path, patch_path, bool(result))
                print(f"[BATCH] {inst.instance_id} run{run_idx}: {'PASS' if result else 'FAIL'}")

            report["instances"][inst.instance_id] = summarize(bits, k_report)
            _refresh_aggregate(report, k_report)
            _save_json(report, report_path)

            if bits and bits[-1] and stop_on_first_pass:
                print(f"[BATCH] {inst.instance_id}: stop-on-first-pass at run{run_idx}.")
                break

        report["instances"][inst.instance_id] = summarize(bits, k_report)
        _refresh_aggregate(report, k_report)
        _save_json(report, report_path)

    _refresh_aggregate(report, k_report)
    _save_json(report, report_path)
    print(f"\n[BATCH] Report written to {report_path}")

    summarize_details(details)
    _save_json(details, details_path)
    print(f"[BATCH] Details written to {details_path}")
    return 0
