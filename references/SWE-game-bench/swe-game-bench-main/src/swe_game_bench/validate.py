"""Instance soundness gate: the hidden test must FAIL on the base commit and
PASS once the developers' real fix (oracle patch) is applied.

This is the curation-time / replication-time check that makes `evaluate`
results meaningful. An instance failing this gate is broken (flaky test,
wrong SHAs, vacuous assertions) and must not be scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import paths
from . import gitrepo
from .dataset import Instance, get_instance, get_repo
from .evaluator import EvalResult, evaluate


@dataclass
class ValidationResult:
    instance_id: str
    base_failed_as_expected: bool
    oracle_passed_as_expected: bool
    base: EvalResult
    oracle: EvalResult
    oracle_patch_path: Path

    @property
    def sound(self) -> bool:
        return self.base_failed_as_expected and self.oracle_passed_as_expected


def get_oracle_patch(instance: Instance, outdir: Path) -> Path:
    """Use the shipped oracle patch when present; otherwise generate it from git history."""
    shipped = instance.oracle_patch_file
    if shipped.exists() and shipped.stat().st_size > 0:
        return shipped
    repo_cfg = get_repo(instance.repo)
    diff = gitrepo.generate_oracle_patch(
        repo_cfg, instance.base_sha, instance.fix_sha, instance.target_files
    )
    generated = outdir / "oracle.patch"
    generated.parent.mkdir(parents=True, exist_ok=True)
    generated.write_text(diff, encoding="utf-8")
    print(f"[validate] Generated oracle patch from git history: {generated}")
    return generated


def validate(instance: Instance | str, outdir: Path | None = None) -> ValidationResult:
    if isinstance(instance, str):
        instance = get_instance(instance)
    run_set = "golden" if instance.benchmark_set == "golden" else "candidates"
    outdir = (
        Path(outdir)
        if outdir
        else paths.runs_root() / run_set / "validate" / instance.instance_id
    )
    outdir.mkdir(parents=True, exist_ok=True)

    oracle_patch = get_oracle_patch(instance, outdir)

    print(f"\n--- {instance.instance_id}: base run ---")
    base = evaluate(instance, skip_patch=True, label="base", outdir=outdir)

    print(f"\n--- {instance.instance_id}: oracle run ---")
    oracle = evaluate(instance, patch_file=oracle_patch, label="oracle", outdir=outdir)

    result = ValidationResult(
        instance_id=instance.instance_id,
        base_failed_as_expected=not base.passed,
        oracle_passed_as_expected=oracle.passed,
        base=base,
        oracle=oracle,
        oracle_patch_path=oracle_patch,
    )

    (outdir / "validation_summary.txt").write_text(
        f"Instance: {instance.instance_id}\n"
        f"Base run: {'FAIL (ok)' if result.base_failed_as_expected else 'PASS (BROKEN GATE)'}\n"
        f"Oracle run: {'PASS (ok)' if result.oracle_passed_as_expected else 'FAIL (BROKEN GATE)'}\n"
        f"Instance sound: {result.sound}\n"
        f"Oracle patch: {oracle_patch}\n",
        encoding="utf-8",
    )

    status = "SOUND" if result.sound else "BROKEN"
    print(
        f"\n[validate] {instance.instance_id}: {status} "
        f"(base {'FAIL ok' if result.base_failed_as_expected else 'PASS!!'}, "
        f"oracle {'PASS ok' if result.oracle_passed_as_expected else 'FAIL!!'})"
    )
    return result
