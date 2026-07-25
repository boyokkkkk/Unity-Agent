"""Evaluate a candidate patch against one benchmark instance.

Pipeline (identical to the original per-repo swe_evaluator.py scripts):
  1. Clone/fetch the repo and check out the base commit (clean).
  2. Run the repo's prepare steps (scrubs) plus any instance-specific extras.
  3. Apply the candidate patch (unless skip_patch), then post-patch steps.
  4. Inject the instance's hidden NUnit test tree.
  5. Run the Unity test runner headlessly; parse the NUnit XML.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import gitrepo, inject, prepare, unity_runner
from .dataset import Instance, get_instance, get_repo


@dataclass
class EvalResult:
    instance_id: str
    label: str
    passed: bool
    exit_code: int
    xml_path: Path
    log_path: Path

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"


def patch_apply_status_path(outdir: Path, label: str) -> Path:
    return Path(outdir) / f"{label}_apply_status.json"


def read_patch_apply_status(outdir: Path, label: str) -> bool | None:
    path = patch_apply_status_path(outdir, label)
    if not path.exists():
        return None
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    applied = status.get("applied")
    return applied if isinstance(applied, bool) else None


def _write_patch_apply_status(
    outdir: Path,
    label: str,
    *,
    applied: bool,
    error: BaseException | None = None,
) -> None:
    status = {
        "applied": applied,
        "error_type": type(error).__name__ if error is not None else None,
        "error": str(error) if error is not None else None,
    }
    patch_apply_status_path(outdir, label).write_text(
        json.dumps(status, indent=2) + "\n",
        encoding="utf-8",
    )


def evaluate(
    instance: Instance | str,
    patch_file: Path | None = None,
    *,
    skip_patch: bool = False,
    label: str | None = None,
    outdir: Path | None = None,
) -> EvalResult:
    if isinstance(instance, str):
        instance = get_instance(instance)
    repo_cfg = get_repo(instance.repo)

    if not skip_patch and patch_file is None:
        raise ValueError("evaluate() needs a patch_file unless skip_patch=True")

    outdir = Path(outdir) if outdir else instance.default_outdir()
    outdir.mkdir(parents=True, exist_ok=True)
    label = label or ("base" if skip_patch else "patched")
    if not skip_patch:
        patch_apply_status_path(outdir, label).unlink(missing_ok=True)

    workdir = gitrepo.ensure_repo(repo_cfg)
    gitrepo.fetch_sha(repo_cfg, instance.base_sha)
    gitrepo.checkout_clean(repo_cfg, instance.base_sha)

    # Some repos keep the Unity project in a subdirectory of the checkout;
    # scrubs and the Unity invocation target the project, git ops the checkout.
    project_dir = workdir / instance.project_subdir if instance.project_subdir else workdir

    prepare.run_steps(repo_cfg, repo_cfg.prepare_steps, project_dir)
    if instance.extra_prepare_steps:
        prepare.run_steps(repo_cfg, instance.extra_prepare_steps, project_dir)

    if not skip_patch:
        try:
            gitrepo.apply_patch(repo_cfg, Path(patch_file))
        except (Exception, SystemExit) as exc:
            _write_patch_apply_status(outdir, label, applied=False, error=exc)
            raise
        _write_patch_apply_status(outdir, label, applied=True)
        if instance.post_patch_steps:
            prepare.run_steps(repo_cfg, instance.post_patch_steps, project_dir)

    inject.inject_tests(instance, repo_cfg, workdir)

    suites = instance.test_suites or [
        {
            "test_platform": instance.test_platform,
            "test_class": instance.test_class,
        }
    ]
    code, xml, log = unity_runner.run_unity_suites(
        workdir=project_dir,
        label=label,
        outdir=outdir,
        suites=suites,
    )

    xml_verdict = unity_runner.xml_says_passed(xml)
    passed = bool(xml_verdict) if xml_verdict is not None else (code == 0)

    (outdir / f"{label}_summary.txt").write_text(
        f"Instance: {instance.instance_id}\nLabel: {label}\nExit code: {code}\n"
        f"Passed: {passed}\nXML: {xml}\nLog: {log}\n",
        encoding="utf-8",
    )

    result = EvalResult(
        instance_id=instance.instance_id,
        label=label,
        passed=passed,
        exit_code=code,
        xml_path=xml,
        log_path=log,
    )
    print(f"\n{result.verdict}  instance={instance.instance_id}  label={label}  exit={code}")
    return result
