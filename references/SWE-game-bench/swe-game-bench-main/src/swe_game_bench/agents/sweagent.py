"""Baseline patch generator: run SWE-agent on one benchmark instance.

The agent receives ONLY the enriched issue text (title + body) plus a shallow
repository-root listing -- no target file, no fix commit, no test code. Any
other repair agent can be benchmarked instead by handing its patch straight to
``swe-game-bench evaluate``; this module just reproduces the paper's baseline.

Ported from the newest per-repo run_swe_agent_issue.py (AoTTG variant), which
includes SWE-agent CLI resolution, tool-bundle verification, and stale-cache
cleanup for SWE-agent's local deployment mode.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from .. import paths
from ..dataset import Instance, RepoConfig, get_repo


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _normalize_env_vars(keys: tuple[str, ...]) -> None:
    for key in keys:
        raw_value = os.getenv(key)
        if raw_value is None:
            continue
        normalized = _strip_wrapping_quotes(raw_value.strip())
        if normalized != raw_value:
            os.environ[key] = normalized


load_dotenv(override=True)
_normalize_env_vars(
    (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
        "SWEAGENT_CMD",
        "SWE_AGENT_SRC_ROOT",
    )
)

DEFAULT_SWEAGENT_CMD = "python -m sweagent" if os.name == "nt" else "python3 -m sweagent"
DEFAULT_SWE_AGENT_SRC_ROOT = "C:/opt/SWE-agent" if os.name == "nt" else "/opt/SWE-agent"
EXPECTED_TOOL_BUNDLE_DIRS = (
    Path("tools/registry"),
    Path("tools/edit_anthropic"),
    Path("tools/review_on_submit_m"),
)
DEFAULT_MODEL = os.getenv("SWE_MODEL", "gpt-5.2")
DEFAULT_MAX_INPUT_TOKENS = os.getenv("SWE_MODEL_MAX_INPUT_TOKENS", "12000")
DEFAULT_MAX_OUTPUT_TOKENS = os.getenv("SWE_MODEL_MAX_OUTPUT_TOKENS", "1500")
DEFAULT_CALL_LIMIT = os.getenv("SWE_MODEL_PER_INSTANCE_CALL_LIMIT", "25")
DEFAULT_MAX_REQUERIES = os.getenv("SWE_AGENT_MAX_REQUERIES", "3")
DEFAULT_TOOL_EXEC_TIMEOUT = os.getenv("SWE_TOOL_EXEC_TIMEOUT", "20")
DEFAULT_TOOL_TOTAL_EXEC_TIMEOUT = os.getenv("SWE_TOOL_TOTAL_EXEC_TIMEOUT", "600")
DEFAULT_TEMPERATURE = os.getenv("SWE_MODEL_TEMPERATURE", "0.4")
MAX_CONTEXT_ROOT_ENTRIES = int(os.getenv("SWE_CONTEXT_ROOT_ENTRIES", "20"))


def _unbounded() -> bool:
    return os.getenv("SWE_AGENT_UNBOUNDED", "").strip().lower() in ("1", "true", "yes", "on")


def load_problem_statement(instance: Instance) -> str:
    path = instance.issue_file
    if not path.exists():
        raise FileNotFoundError(
            f"Missing issue description: {path}\n"
            f"Run: swe-game-bench enrich {instance.instance_id}"
        )
    return path.read_text(encoding="utf-8").strip()


def find_patch_in_output(output_dir: Path, instance_id: str) -> Path | None:
    """SWE-agent saves the patch in version-dependent locations; search the common ones."""
    candidates = [
        output_dir / "patches" / f"{instance_id}.patch",
        output_dir / f"{instance_id}.patch",
        output_dir / "patch.diff",
        output_dir / "model.patch",
        *output_dir.rglob("*.patch"),
        *output_dir.rglob("*.diff"),
    ]
    for c in candidates:
        if isinstance(c, Path) and c.exists() and c.stat().st_size > 0:
            return c
    return None


def _format_cmd(cmd: list[str]) -> str:
    return " ".join(str(x) for x in cmd)


def _capture_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=os.environ.copy(),
    )


def _resolve_sweagent_command() -> list[str]:
    raw_cmd = os.getenv("SWEAGENT_CMD", "").strip()
    candidate_strings = [raw_cmd] if raw_cmd else [DEFAULT_SWEAGENT_CMD]
    if not raw_cmd:
        if os.name == "nt":
            candidate_strings.extend(["py -3 -m sweagent", "python -m sweagent"])
        else:
            candidate_strings.extend(["python3.11 -m sweagent", "python3 -m sweagent", "python -m sweagent"])

    failures: list[str] = []
    seen: set[str] = set()
    for candidate in candidate_strings:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        cmd = shlex.split(candidate)
        try:
            probe = _capture_command(cmd + ["--help"])
        except FileNotFoundError as exc:
            failures.append(f"- {_format_cmd(cmd)} -> {exc}")
            continue

        if probe.returncode == 0:
            print(f"[SWE-agent] Resolved SWEAGENT_CMD: {_format_cmd(cmd)}")
            return cmd

        summary = probe.stdout.strip().splitlines()
        tail = summary[-1] if summary else "(no output)"
        failures.append(f"- {_format_cmd(cmd)} -> exit {probe.returncode}: {tail}")

    guidance = (
        "The configured SWEAGENT_CMD is not runnable."
        if raw_cmd
        else "No runnable SWE-agent command was found."
    )
    raise RuntimeError(
        f"{guidance}\n"
        "Make sure SWE-agent is installed from source and SWEAGENT_CMD points at that interpreter.\n"
        "Tried:\n" + "\n".join(failures)
    )


def _infer_sweagent_module_path(resolved_cmd: list[str]) -> Path | None:
    if "-m" not in resolved_cmd:
        return None
    module_flag_idx = resolved_cmd.index("-m")
    if module_flag_idx == 0 or module_flag_idx + 1 >= len(resolved_cmd):
        return None
    if resolved_cmd[module_flag_idx + 1] != "sweagent":
        return None
    interpreter_cmd = resolved_cmd[:module_flag_idx]
    probe = _capture_command(
        interpreter_cmd
        + ["-c", "from pathlib import Path; import sweagent; print(Path(sweagent.__file__).resolve())"]
    )
    if probe.returncode != 0:
        return None
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if not lines:
        return None
    try:
        return Path(lines[-1])
    except OSError:
        return None


def _resolve_sweagent_tool_root(resolved_cmd: list[str]) -> Path:
    src_root = Path(os.getenv("SWE_AGENT_SRC_ROOT", DEFAULT_SWE_AGENT_SRC_ROOT))
    candidates: list[Path] = []
    if str(src_root).strip():
        candidates.append(src_root)
    module_path = _infer_sweagent_module_path(resolved_cmd)
    if module_path is not None:
        candidates.extend(list(module_path.parents[:6]))

    checked_paths: list[str] = []
    seen: set[str] = set()
    for root in candidates:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        checked_paths.append(key)
        if all((root / rel_path).is_dir() for rel_path in EXPECTED_TOOL_BUNDLE_DIRS):
            print(f"[SWE-agent] Verified tool bundle root: {root}")
            return root

    expected = ", ".join(str(path) for path in EXPECTED_TOOL_BUNDLE_DIRS)
    checked = ", ".join(checked_paths) if checked_paths else "(no candidate roots)"
    raise RuntimeError(
        "Could not locate SWE-agent tool bundle root.\n"
        f"Expected directories: {expected}\n"
        f"Checked roots: {checked}\n"
        "Set SWE_AGENT_SRC_ROOT to the cloned SWE-agent repository if needed."
    )


def _git_capture(repo_cfg: RepoConfig, args: list[str]) -> str:
    workdir = repo_cfg.resolved_workdir()
    safe_dir = str(workdir).replace("\\", "/")
    env = os.environ.copy()
    if repo_cfg.git_lfs_skip_smudge:
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
    result = subprocess.run(
        ["git", "-c", f"safe.directory={safe_dir}", *args],
        cwd=workdir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed:\n  git {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout


def build_repo_context(instance: Instance, repo_cfg: RepoConfig) -> str:
    """Shallow repo-root listing at the base commit; the only repo hint the agent gets."""
    from .. import gitrepo

    gitrepo.ensure_repo(repo_cfg)
    try:
        output = _git_capture(repo_cfg, ["ls-tree", "--name-only", instance.base_sha])
        root_entries = [line.strip() for line in output.splitlines() if line.strip()][:MAX_CONTEXT_ROOT_ENTRIES]
    except RuntimeError:
        root_entries = []

    context_lines = [
        "Repository context:",
        f"- Base commit: {instance.base_sha}",
        "",
        "Repository root snapshot:",
    ]
    if root_entries:
        context_lines.extend(f"- {entry}" for entry in root_entries)
    else:
        context_lines.append("- [Unavailable]")
    return "\n".join(context_lines)


def _ensure_root_alias(workdir: Path) -> None:
    """SWE-agent's preexisting-repo mode expects the repo at /<repo_name>;
    our checkouts live under /tmp, so expose a root-level symlink."""
    if os.name == "nt":
        return
    alias = Path("/") / workdir.name
    if alias.is_symlink() or alias.exists():
        return
    try:
        alias.symlink_to(workdir)
        print(f"[SWE-agent] Linked {alias} -> {workdir}")
    except OSError as exc:
        print(f"[SWE-agent][WARN] Could not create {alias}: {exc}")


def _attempt_sweagent_run(cmd: list[str], raw_outdir: Path) -> tuple[int, str, Path]:
    if raw_outdir.exists():
        shutil.rmtree(raw_outdir)
    raw_outdir.mkdir(parents=True, exist_ok=True)

    # SWE-agent local deployment copies its tools to /root/tools on each run.
    # shutil.copytree fails if the destination already exists, so clean it first.
    tools_dir = Path("/root/tools")
    if tools_dir.exists():
        shutil.rmtree(tools_dir)

    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        env=os.environ.copy(),
    )
    return result.returncode, result.stdout, raw_outdir


def _cleanup_stale_local_repo_cache(repo_cfg: RepoConfig) -> None:
    """SWE-agent local deployment may leave a stale /owner__repo.git cache that breaks reruns."""
    if "/" not in repo_cfg.gh_repo:
        return
    cache_dir = Path("/") / f"{repo_cfg.gh_repo.replace('/', '__')}.git"
    if cache_dir.exists() and cache_dir.is_dir():
        try:
            shutil.rmtree(cache_dir)
            print(f"[SWE-agent] Removed stale cache directory: {cache_dir}")
        except Exception as e:
            print(f"[SWE-agent][WARN] Could not remove stale cache directory {cache_dir}: {e}")


def _cleanup_stale_tool_bundle_dirs() -> None:
    for rel in EXPECTED_TOOL_BUNDLE_DIRS:
        p = Path("/root") / rel
        if p.exists() and p.is_dir():
            try:
                shutil.rmtree(p)
                print(f"[SWE-agent] Removed stale tool bundle directory: {p}")
            except Exception as e:
                print(f"[SWE-agent][WARN] Could not remove stale tool bundle directory {p}: {e}")


def _sweagent_config_path() -> Path:
    return paths.configs_dir() / "sweagent_unity.yaml"


def _build_candidate_commands(
    sweagent_cmd: list[str],
    instance: Instance,
    repo_cfg: RepoConfig,
    model: str,
    ps_file: Path,
    raw_outdir: Path,
) -> list[list[str]]:
    base = list(sweagent_cmd) + ["run"]
    config = _sweagent_config_path()
    config_args = [f"--config={config}"] if config.exists() else []
    limit_args = [] if _unbounded() else [
        f"--agent.model.max_input_tokens={DEFAULT_MAX_INPUT_TOKENS}",
        f"--agent.model.max_output_tokens={DEFAULT_MAX_OUTPUT_TOKENS}",
        f"--agent.model.per_instance_call_limit={DEFAULT_CALL_LIMIT}",
        f"--agent.max_requeries={DEFAULT_MAX_REQUERIES}",
        f"--agent.tools.execution_timeout={DEFAULT_TOOL_EXEC_TIMEOUT}",
        f"--agent.tools.total_execution_timeout={DEFAULT_TOOL_TOTAL_EXEC_TIMEOUT}",
    ]
    workdir = repo_cfg.resolved_workdir()
    if os.name == "nt":
        repo_args = [
            f"--env.repo.path={workdir}",
            f"--env.repo.base_commit={instance.base_sha}",
            "--env.repo.type=local",
            "--env.deployment.type=local",
        ]
    else:
        # PreExistingRepoConfig skips SWE-agent's local-repo upload/copy step.
        repo_args = [
            f"--env.repo.repo_name={workdir.name}",
            f"--env.repo.base_commit={instance.base_sha}",
            "--env.repo.type=preexisting",
            "--env.deployment.type=local",
        ]

    model_args = [
        f"--agent.model.name={model}",
        f"--agent.model.temperature={DEFAULT_TEMPERATURE}",
    ]
    # Keep every attempt on the Unity config so we never fall back to the default Python prompt.
    return [
        base + config_args + model_args + limit_args + repo_args + [
            "--problem_statement.type=text_file",
            f"--problem_statement.path={ps_file}",
            f"--output_dir={raw_outdir}",
        ],
        base + config_args + model_args + limit_args + repo_args + [
            f"--problem_statement.path={ps_file}",
            f"--output_dir={raw_outdir}",
        ],
    ]


def generate_patch(instance: Instance, model: str | None = None, outdir: Path | None = None) -> Path:
    """Run SWE-agent on one instance; return the path to the saved patch (swe_agent.patch)."""
    repo_cfg = get_repo(instance.repo)
    model = model or DEFAULT_MODEL
    outdir = Path(outdir) if outdir else instance.default_outdir() / "swe_agent"
    outdir.mkdir(parents=True, exist_ok=True)

  
    from ..unity_runner import kill_stray_unity

    kill_stray_unity()

    problem_statement = load_problem_statement(instance)
    sweagent_instance_id = f"{repo_cfg.gh_repo.lower().replace('/', '__')}-{instance.issue_number}"

    repo_context = build_repo_context(instance, repo_cfg)
    _ensure_root_alias(repo_cfg.resolved_workdir())

    from .. import gitrepo

    gitrepo.fetch_sha(repo_cfg, instance.base_sha)
    gitrepo.checkout_clean(repo_cfg, instance.base_sha)
    constrained_problem = (
        f"{problem_statement}\n\n"
        "Constraints:\n"
        "- Do not create helper scripts or extra files.\n"
        "- Make the smallest possible edit that fixes the issue.\n"
        "- Use grep, find, or cat to explore the repository and locate the relevant code.\n\n"
        f"{repo_context}"
    )

    ps_file = outdir / "problem_statement.txt"
    ps_file.write_text(constrained_problem, encoding="utf-8")

    instance_file = outdir / "instance.json"
    instance_file.write_text(
        json.dumps(
            {
                "repo": repo_cfg.gh_repo,
                "instance_id": sweagent_instance_id,
                "base_commit": instance.base_sha,
                "problem_statement": constrained_problem,
                "hints_text": "",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    raw_outdir = outdir / "_sweagent_raw"
    log_path = outdir / "swe_agent_run.log"
    log_chunks: list[str] = []

    try:
        sweagent_cmd = _resolve_sweagent_command()
        _resolve_sweagent_tool_root(sweagent_cmd)
    except Exception as exc:
        log_path.write_text(f"[SWE-agent][SETUP ERROR] {exc}\n", encoding="utf-8")
        raise

    print(f"\n[SWE-agent] Instance {instance.instance_id} | model={model}")
    raw_patch: Path | None = None
    for attempt_idx, cmd in enumerate(
        _build_candidate_commands(sweagent_cmd, instance, repo_cfg, model, ps_file, raw_outdir),
        start=1,
    ):
        _cleanup_stale_local_repo_cache(repo_cfg)
        _cleanup_stale_tool_bundle_dirs()
        print(f"\n[SWE-agent] Attempt {attempt_idx}")
        print("CMD:", _format_cmd(cmd))
        rc, out, output_root = _attempt_sweagent_run(cmd, raw_outdir)
        raw_patch = find_patch_in_output(output_root, sweagent_instance_id)
        log_chunks.append(
            f"\n=== Attempt {attempt_idx} | exit={rc} ===\nCMD: {_format_cmd(cmd)}\n{out}\n"
        )
        print(out)
        out_lc = out.lower()
        if "rate_limit_exceeded" in out_lc or "request too large" in out_lc:
            log_path.write_text("".join(log_chunks), encoding="utf-8")
            raise RuntimeError(
                "SWE-agent run hit provider token/rate limits. "
                "Try a smaller model or lower SWE_MODEL_MAX_INPUT_TOKENS."
            )
        if raw_patch is not None:
            if rc != 0:
                print(f"[WARN] SWE-agent exited {rc} but produced a patch (attempt {attempt_idx}).")
            break

    log_path.write_text("".join(log_chunks), encoding="utf-8")
    if raw_patch is None:
        raise RuntimeError(
            "SWE-agent did not produce a patch in any attempted CLI configuration.\n"
            f"Check log: {log_path}"
        )

    patch_text = raw_patch.read_text(encoding="utf-8", errors="replace")
    if not patch_text.strip():
        raise RuntimeError("SWE-agent produced an empty patch.")

    raw_copy = outdir / "swe_agent_raw.patch"
    if raw_patch != raw_copy:
        shutil.copy2(raw_patch, raw_copy)
    final_patch = outdir / "swe_agent.patch"
    final_patch.write_text(patch_text, encoding="utf-8")

    print(f"\n[OK] Patch saved to: {final_patch}")
    print(f"     Size: {final_patch.stat().st_size} bytes")
    print("\nNext - evaluate the patch:")
    print(f"  swe-game-bench evaluate --instance-id {instance.instance_id} --patch-file {final_patch}")
    return final_patch
