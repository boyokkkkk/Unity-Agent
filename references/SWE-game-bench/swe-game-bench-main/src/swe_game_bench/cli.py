"""swe-game-bench command-line interface.

Typical replication flow:
    swe-game-bench list
    swe-game-bench prepare  --instance-id fungus-879   # build + start container
    swe-game-bench validate --instance-id fungus-879   # instance soundness gate
    swe-game-bench evaluate --instance-id fungus-879 --patch-file my.patch
    swe-game-bench pass-at-k --instances fungus-879 --k 10 --model gpt-5.2
    swe-game-bench report

Container-bound commands (validate/evaluate/generate, and pass-at-k through
them) auto-detect where they are: outside the containers they forward
themselves into the selected backend. Use --backend docker/apptainer, --docker,
--apptainer, or --local to force a mode; --fresh requests disposable execution.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from . import paths


def cmd_list(args) -> int:
    from .dataset import load_instances

    instances = load_instances()
    if args.repo:
        instances = [i for i in instances if i.repo == args.repo]
    if args.benchmark_set:
        instances = [i for i in instances if i.benchmark_set == args.benchmark_set]
    print(f"{'instance_id':<22} {'set':<8} {'unity':<14} {'platform':<18} test_class")
    for inst in instances:
        if inst.test_suites:
            platform = ",".join(suite["test_platform"] for suite in inst.test_suites)
            test_class = ";".join(suite["test_class"] for suite in inst.test_suites)
        else:
            platform = inst.test_platform
            test_class = inst.test_class
        print(
            f"{inst.instance_id:<22} {inst.benchmark_set:<8} "
            f"{inst.unity_bucket:<14} {platform:<18} {test_class}"
        )
    print(f"\n{len(instances)} instance(s)")
    return 0


def cmd_prepare(args) -> int:
    from .dataset import get_instance, get_repo

    inst = get_instance(args.instance_id)
    backend = _container_backend(args)
    ctl = _container_ctl(backend)
    return ctl.prepare_instance(inst, get_repo(inst.repo))


def _container_backend(args) -> str:
    if getattr(args, "apptainer", False):
        return "apptainer"
    if getattr(args, "docker", False):
        return "docker"
    backend = (getattr(args, "backend", None) or os.getenv("SWE_GAME_BENCH_BACKEND", "docker")).strip().lower()
    if backend in {"singularity", "apptainer"}:
        return "apptainer"
    if backend == "docker":
        return "docker"
    raise SystemExit(f"[ERROR] Unknown backend '{backend}'. Use docker or apptainer.")


def _container_ctl(backend: str):
    if backend == "docker":
        from . import docker_ctl

        return docker_ctl
    if backend == "apptainer":
        from . import apptainer_ctl

        return apptainer_ctl
    raise SystemExit(f"[ERROR] Unknown backend '{backend}'.")


def _reexec_in_container(args, cli_args: list[str]) -> int:
    from .dataset import get_instance, get_repo

    inst = get_instance(args.instance_id)
    repo_cfg = get_repo(inst.repo)
    backend = _container_backend(args)
    ctl = _container_ctl(backend)

    if backend == "apptainer":
        print(f"[apptainer] Unity {inst.unity_bucket} â€” one-shot SIF execution")
        return ctl.exec_ephemeral(inst, repo_cfg, cli_args)

    if getattr(args, "fresh", False):
        print(f"[docker] Unity {inst.unity_bucket} â€” fresh disposable container")
        rc = ctl.exec_ephemeral(inst, repo_cfg, cli_args)
        return rc
    name = ctl.container_name(repo_cfg.key, inst.unity_bucket)
    print(f"[docker] Unity {inst.unity_bucket} â€” {name}")

    if not ctl.container_running(name):
        import time as _time

        print(f"[docker] {name} is not running â€” preparing (build + start)â€¦")
        since = str(int(_time.time()))
        rc = ctl.prepare_instance(inst, repo_cfg)
        if rc != 0:
            print(
                f"\n[hint] Could not build/start {name}. Check that the Unity image can "
                f"build (LICENSE_PATH and the Unity base image must be configured)."
            )
            return rc
 
        print(f"[docker] waiting for Unity license activation in {name}â€¦")
        if ctl.wait_for_license(name, since):
            print("[docker] license active.")
        else:
            print(
                f"\n[docker][WARN] license activation didn't confirm for {name} "
                f"(timeout or OOM-killed). The run may fail to license â€” if so, free "
                f"RAM/add swap and re-run."
            )
    rc = ctl.exec_cli(inst, repo_cfg, cli_args)
    if rc != 0:
        print(
            f"\n[hint] If the error above says the container does not exist or is not "
            f"running, start it first:\n       swe-game-bench prepare --instance-id {args.instance_id}"
        )
    return rc


def _use_container(args) -> bool:
    """Unity-running commands execute locally only where Unity exists (inside the
    container); anywhere else they are auto-forwarded through the selected backend."""
    if getattr(args, "local", False):
        return False
    if getattr(args, "docker", False) or getattr(args, "apptainer", False) or getattr(args, "backend", None):
        return True

    unity = Path(os.getenv("UNITY", "/opt/unity/Editor/Unity"))
    return not unity.exists()


def cmd_evaluate(args) -> int:
    if not args.skip_patch and not args.patch_file:
        print("[ERROR] evaluate needs --patch-file (or --skip-patch).")
        return 2

    if _use_container(args):
        backend = _container_backend(args)
        ctl = _container_ctl(backend)

        cli_args = ["evaluate", "--local", "--instance-id", args.instance_id]
        if args.skip_patch:
            cli_args.append("--skip-patch")
        else:
            # The container only sees paths under the package root (mounted at
            # /pipeline). If the patch already lives there (e.g. pass-at-k's
            # runs/...), hand it over as-is. Only a patch from outside the root
            # needs staging into a container-visible location.
            patch = Path(args.patch_file)
            try:
                in_container_patch = ctl.to_container_path(patch)
            except ValueError:
                staged = paths.runs_root() / args.instance_id / "incoming.patch"
                staged.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(patch, staged)
                in_container_patch = ctl.to_container_path(staged)
            cli_args += ["--patch-file", in_container_patch]
        if args.label:
            cli_args += ["--label", args.label]
        if args.outdir:
            cli_args += ["--outdir", ctl.to_container_path(Path(args.outdir))]
        return _reexec_in_container(args, cli_args)

    from .evaluator import evaluate

    result = evaluate(
        args.instance_id,
        patch_file=Path(args.patch_file) if args.patch_file else None,
        skip_patch=args.skip_patch,
        label=args.label,
        outdir=Path(args.outdir) if args.outdir else None,
    )
    return 0 if result.passed else 1


def cmd_validate(args) -> int:
    if _use_container(args):
        cli_args = ["validate", "--local", "--instance-id", args.instance_id]
        if args.outdir:
            ctl = _container_ctl(_container_backend(args))

            cli_args += ["--outdir", ctl.to_container_path(Path(args.outdir))]
        return _reexec_in_container(args, cli_args)

    from .validate import validate

    result = validate(args.instance_id, outdir=Path(args.outdir) if args.outdir else None)
    return 0 if result.sound else 1


def cmd_generate(args) -> int:
    if _use_container(args):
        ctl = _container_ctl(_container_backend(args))

        cli_args = ["generate", "--local", "--instance-id", args.instance_id]
        if args.model:
            cli_args += ["--model", args.model]
        if args.outdir:
            cli_args += ["--outdir", ctl.to_container_path(Path(args.outdir))]
        return _reexec_in_container(args, cli_args)

    from .agents.sweagent import generate_patch
    from .dataset import get_instance

    inst = get_instance(args.instance_id)
    try:
        generate_patch(inst, model=args.model, outdir=Path(args.outdir) if args.outdir else None)
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1
    return 0


def cmd_pass_at_k(args) -> int:
    from .passk import run_pass_at_k

    os.environ["SWE_GAME_BENCH_BACKEND"] = _container_backend(args)
    instance_ids = None
    if args.instances:
        instance_ids = [tok.strip() for tok in args.instances.split(",") if tok.strip()]
    if not args.model:
        from .agents.sweagent import DEFAULT_MODEL

        args.model = DEFAULT_MODEL
    return run_pass_at_k(
        instance_ids,
        k=args.k,
        model=args.model,
        runs_root=Path(args.runs_root) if args.runs_root else None,
        benchmark_set=args.benchmark_set,
        start_run=args.start_run,
        skip_existing=args.skip_existing,
        stop_on_first_pass=args.stop_on_first_pass,
        gen_timeout=args.gen_timeout,
        eval_timeout=args.eval_timeout,
        cleanup_workdir=not args.no_cleanup_workdir,
    )


def cmd_evaluate_predictions(args) -> int:
    from .predictions import evaluate_predictions

    if args.local:
        backend = None
    elif args.apptainer or args.backend == "apptainer":
        backend = "apptainer"
    else:
        backend = "docker"
    if backend:
        os.environ["SWE_GAME_BENCH_BACKEND"] = backend

    instance_ids = None
    if args.instances:
        instance_ids = [tok.strip() for tok in args.instances.split(",") if tok.strip()]
    try:
        return evaluate_predictions(
            predictions_file=Path(args.predictions),
            agent=args.agent,
            model=args.model,
            temperature=args.temperature,
            benchmark_set=args.benchmark_set,
            instance_ids=instance_ids,
            k=args.k,
            runs_root=Path(args.runs_root) if args.runs_root else None,
            experiment=args.experiment,
            allow_incomplete=args.allow_incomplete,
            skip_existing=args.skip_existing,
            eval_timeout=args.eval_timeout,
            local=args.local,
            forced_backend=backend,
            fresh=args.fresh,
            verified=args.verified,
            logs_url=args.logs_url,
        )
    except Exception as e:
        print(f"[ERROR] {e}")
        return 1


def cmd_enrich(args) -> int:
    from .enrich import enrich

    return enrich(args.instance_ids or None, force=args.force)


def cmd_oracle(args) -> int:
    """Generate and store oracle patches into benchmark/oracle_patches/."""
    from . import gitrepo
    from .dataset import get_instance, get_repo, load_instances

    instances = [get_instance(args.instance_id)] if args.instance_id else load_instances()
    outdir = paths.oracle_patches_dir()
    outdir.mkdir(parents=True, exist_ok=True)
    failed = []
    for inst in instances:
        target = outdir / f"{inst.instance_id}.patch"
        if target.exists() and not args.force:
            print(f"[oracle] {inst.instance_id}: already present, skipping")
            continue
        try:
            diff = gitrepo.generate_oracle_patch(
                get_repo(inst.repo), inst.base_sha, inst.fix_sha, inst.target_files
            )
        except Exception as e:
            print(f"[oracle] {inst.instance_id}: FAILED ({e})")
            failed.append(inst.instance_id)
            continue
        target.write_text(diff, encoding="utf-8")
        print(f"[oracle] {inst.instance_id}: wrote {target}")
    if failed:
        print(f"\n[oracle] {len(failed)} failure(s): {', '.join(failed)}")
    return 1 if failed else 0


def cmd_report(args) -> int:
    """Build issue-level reports and the global leaderboard index."""
    from .reporting import build_reports

    return build_reports(
        runs_root=Path(args.runs_root) if args.runs_root else None,
        model=args.model,
        temperature=args.temperature,
        benchmark_set=args.benchmark_set,
        include_incomplete=args.include_incomplete,
    )


def cmd_docker(args) -> int:
    from . import docker_ctl

    if args.docker_cmd == "generate":
        docker_ctl.generate_compose()
        return 0
    if args.docker_cmd == "build":
        return docker_ctl.build(args.repo, args.bucket)
    if args.docker_cmd == "up":
        return docker_ctl.up(args.repo, args.bucket)
    if args.docker_cmd == "down":
        return docker_ctl.down()
    if args.docker_cmd == "shell":
        if not (args.repo and args.bucket):
            print("[ERROR] docker shell needs --repo and --bucket")
            return 2
        return docker_ctl.shell(args.repo, args.bucket)
    return 2


def cmd_apptainer(args) -> int:
    from . import apptainer_ctl

    if args.apptainer_cmd == "image":
        if not (args.repo and args.bucket):
            print("[ERROR] apptainer image needs --repo and --bucket")
            return 2
        print(apptainer_ctl.image_path_for(args.repo, args.bucket))
        return 0
    if args.apptainer_cmd == "shell":
        if not (args.repo and args.bucket):
            print("[ERROR] apptainer shell needs --repo and --bucket")
            return 2
        return apptainer_ctl.shell(args.repo, args.bucket)
    return 2


def _add_backend_args(sp: argparse.ArgumentParser, *, include_local: bool = True) -> None:
    sp.add_argument("--backend", choices=["docker", "apptainer"], default=None,
                    help="Container backend (default: docker unless a command documents otherwise)")
    sp.add_argument("--docker", action="store_true",
                    help="Shortcut for --backend docker")
    sp.add_argument("--apptainer", action="store_true",
                    help="Shortcut for --backend apptainer")
    if include_local:
        sp.add_argument("--local", action="store_true",
                        help="Force running in the current environment, never through a container backend")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="swe-game-bench", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="List benchmark instances")
    sp.add_argument("--repo", help="Filter by repo key (e.g. fungus)")
    sp.add_argument("--set", dest="benchmark_set", help="Filter by benchmark set (e.g. golden)")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("prepare", help="Build + start the Unity container for an instance")
    sp.add_argument("--instance-id", required=True)
    _add_backend_args(sp, include_local=False)
    sp.set_defaults(func=cmd_prepare)

    sp = sub.add_parser("evaluate", help="Evaluate a candidate patch against an instance")
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--patch-file", help="Unified diff produced by any repair agent")
    sp.add_argument("--skip-patch", action="store_true", help="Run without a patch (base-only)")
    sp.add_argument("--label", default=None, help="Label for output files (default: patched/base)")
    sp.add_argument("--outdir", default=None)
    _add_backend_args(sp)
    sp.add_argument("--fresh", action="store_true",
                    help="Run in a disposable container (clean state, parallel-safe)")
    sp.set_defaults(func=cmd_evaluate)

    sp = sub.add_parser("validate", help="Instance soundness gate: base FAIL + oracle PASS")
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--outdir", default=None)
    _add_backend_args(sp)
    sp.add_argument("--fresh", action="store_true",
                    help="Run in a disposable container (clean state, parallel-safe)")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("generate", help="Run the SWE-agent baseline to produce a patch")
    sp.add_argument("--instance-id", required=True)
    sp.add_argument("--model", default=None)
    sp.add_argument("--outdir", default=None)
    _add_backend_args(sp)
    sp.add_argument("--fresh", action="store_true",
                    help="Run in a disposable container (clean state, parallel-safe)")
    sp.set_defaults(func=cmd_generate)

    sp = sub.add_parser("pass-at-k", help="k generate+evaluate runs per instance")
    sp.add_argument(
        "--instances",
        default=None,
        help="Comma-separated instance IDs (must all belong to the same benchmark set)",
    )
    sp.add_argument("--set", dest="benchmark_set", help="Run only one benchmark set (e.g. golden)")
    sp.add_argument("--k", type=int, default=10)
    sp.add_argument("--model", default=None,
                    help="LLM for the SWE-agent baseline (default: SWE_MODEL from .env, else gpt-5.2)")
    sp.add_argument("--runs-root", default=None)
    sp.add_argument("--start-run", type=int, default=1)
    sp.add_argument("--skip-existing", action="store_true")
    sp.add_argument("--stop-on-first-pass", action="store_true")
    sp.add_argument("--gen-timeout", type=int, default=1800)
    sp.add_argument("--eval-timeout", type=int, default=2700)
    sp.add_argument("--no-cleanup-workdir", action="store_true")
    _add_backend_args(sp, include_local=False)
    sp.set_defaults(func=cmd_pass_at_k)

    sp = sub.add_parser(
        "evaluate-predictions",
        help="Evaluate externally generated JSONL patch predictions",
    )
    sp.add_argument(
        "--predictions",
        required=True,
        help="JSONL file with instance_id, run_id, and model_patch fields",
    )
    sp.add_argument("--set", dest="benchmark_set", help="Benchmark set: golden, candidates, or core")
    sp.add_argument(
        "--instances",
        default=None,
        help="Comma-separated instance IDs for local smoke tests or partial runs",
    )
    sp.add_argument("--k", type=int, default=10, help="Required attempts per instance (default: 10)")
    sp.add_argument(
        "--agent",
        default=None,
        help="Optional metadata override for manual/incomplete runs; official JSONL rows must include agent",
    )
    sp.add_argument(
        "--model",
        default=None,
        help="Optional metadata override for manual/incomplete runs; official JSONL rows must include model",
    )
    sp.add_argument(
        "--temperature",
        default=None,
        help=(
            "Optional sampling-temperature metadata override. Temperature may be "
            "omitted when it does not apply"
        ),
    )
    sp.add_argument(
        "--experiment",
        default=None,
        help="Experiment directory id (default: <agent>_<model>[_t<temperature>])",
    )
    sp.add_argument(
        "--runs-root",
        default=None,
        help=(
            "Output root for this experiment. Default: "
            "runs/<golden|candidates>/predictions/<experiment>"
        ),
    )
    sp.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Allow missing instances or fewer than k contiguous runs; not leaderboard-complete",
    )
    sp.add_argument("--skip-existing", action="store_true", help="Reuse matching existing XML results")
    sp.add_argument("--eval-timeout", type=int, default=2700)
    sp.add_argument(
        "--verified",
        action="store_true",
        help="Mark report as maintainer-verified (usually only set after an official rerun)",
    )
    sp.add_argument("--logs-url", default=None, help="Optional public URL for logs/trajectories")
    _add_backend_args(sp)
    sp.add_argument(
        "--fresh",
        action="store_true",
        help="Run each patch in a disposable container through the selected backend",
    )
    sp.set_defaults(func=cmd_evaluate_predictions)

    sp = sub.add_parser("enrich", help="(Re)generate issue descriptions from GitHub")
    sp.add_argument("instance_ids", nargs="*", help="Instance IDs (default: all stale/missing)")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser("oracle", help="Generate oracle patches into benchmark/oracle_patches/")
    sp.add_argument("--instance-id", default=None, help="One instance (default: all)")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_oracle)

    sp = sub.add_parser("report", help="Aggregate pass@k reports into a leaderboard table")
    sp.add_argument("--runs-root", default=None)
    sp.add_argument("--model", default=None, help="Only report this exact model name")
    sp.add_argument("--temperature", default=None, help="Only report this sampling temperature")
    sp.add_argument(
        "--set",
        dest="benchmark_set",
        choices=["candidates", "golden"],
        help="Only report one benchmark set",
    )
    sp.add_argument(
        "--include-incomplete",
        action="store_true",
        help="Include incomplete experiments in runs/leaderboard.{json,csv} for diagnostics",
    )
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("docker", help="Manage the Unity evaluation containers")
    sp.add_argument("docker_cmd", choices=["generate", "build", "up", "down", "shell"])
    sp.add_argument("--repo", default=None)
    sp.add_argument("--bucket", default=None)
    sp.set_defaults(func=cmd_docker)

    sp = sub.add_parser("apptainer", help="Inspect/run Apptainer SIF images")
    sp.add_argument("apptainer_cmd", choices=["image", "shell"])
    sp.add_argument("--repo", default=None)
    sp.add_argument("--bucket", default=None)
    sp.set_defaults(func=cmd_apptainer)

    return p


def _load_env_file() -> None:
    """Load <repo root>/.env so tokens/settings work without exporting them.
    Real environment variables take precedence over the file."""
    try:
        from dotenv import load_dotenv

        load_dotenv(paths.data_root().parent / ".env")
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    #We load .env first so Docker, Unity, and agent settings are ready.
    _load_env_file()
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        # Ctrl+C can leave Unity running in the container, so we clean it up.
        try:
            from .unity_runner import kill_stray_unity

            kill_stray_unity()
        except Exception:
            pass
        print("\n[interrupted]")
        return 130


if __name__ == "__main__":
    sys.exit(main())
