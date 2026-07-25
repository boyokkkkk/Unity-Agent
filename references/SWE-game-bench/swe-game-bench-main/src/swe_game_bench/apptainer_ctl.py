from __future__ import annotations
import os
import shlex
import shutil
import subprocess
from pathlib import Path

from . import paths
from .dataset import Instance, RepoConfig


def package_root() -> Path:
    return paths.data_root().parent


def runtime() -> str:
    configured = (
        os.getenv("SWE_GAME_BENCH_APPTAINER_BIN")
        or os.getenv("APPTAINER_BIN")
        or ""
    ).strip()
    if configured:
        return configured
    if shutil.which("apptainer"):
        return "apptainer"
    if shutil.which("singularity"):
        return "singularity"
    return "apptainer"


def image_dir() -> Path:
    configured = (
        os.getenv("SWE_GAME_BENCH_APPTAINER_IMAGE_DIR")
        or os.getenv("APPTAINER_IMAGE_DIR")
        or ""
    ).strip()
    if configured:
        return Path(configured)
    return paths.data_root() / "apptainer" / "images"


def image_path_for(repo_key: str, bucket: str) -> Path:
    override = os.getenv("SWE_GAME_BENCH_APPTAINER_IMAGE", "").strip()
    if override:
        return Path(override)
    return image_dir() / f"swegb-{repo_key}-{bucket}.sif"


def image_path(instance: Instance, repo_cfg: RepoConfig) -> Path:
    return image_path_for(repo_cfg.key, instance.unity_bucket)


def instance_name(repo_key: str, bucket: str) -> str:
    return f"swegb-{repo_key}-{bucket}"


def to_container_path(host_path: Path) -> str:
    path = Path(host_path).resolve()
    root = package_root().resolve()
    try:
        rel = path.relative_to(root)
        return "/pipeline/" + str(rel).replace("\\", "/")
    except ValueError:
        pass

    runs_root = paths.runs_root().resolve()
    try:
        rel = path.relative_to(runs_root)
        return "/pipeline/runs/" + str(rel).replace("\\", "/")
    except ValueError:
        raise ValueError(f"Path is not visible inside Apptainer: {host_path}") from None


def _license_path() -> str:
    return os.getenv("LICENSE_PATH", str(package_root() / "unity_license_data"))


def _host_scratch_dir(repo_cfg: RepoConfig, bucket: str, kind: str) -> Path:
    env_key = f"SWE_GAME_BENCH_APPTAINER_{kind.upper()}"
    configured = os.getenv(env_key, "").strip()
    if configured:
        base = Path(configured)
    else:
        base = paths.runs_root() / f"apptainer_{kind.lower()}"
    path = base / f"{repo_cfg.key}-{bucket}-{os.getpid()}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _extra_binds() -> list[str]:
    raw = os.getenv("SWE_GAME_BENCH_APPTAINER_BINDS", "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _bind_args(repo_cfg: RepoConfig, bucket: str) -> list[str]:
    runs_root = paths.runs_root()
    runs_root.mkdir(parents=True, exist_ok=True)
    tmp_dir = _host_scratch_dir(repo_cfg, bucket, "tmp")
    root_dir = _host_scratch_dir(repo_cfg, bucket, "home")
    binds = [
        f"{package_root()}:/pipeline",
        f"{runs_root}:/pipeline/runs",
        f"{_license_path()}:/usr/share/unity3d/Unity",
        f"{tmp_dir}:/tmp",
        f"{root_dir}:/root",
        *_extra_binds(),
    ]
    args: list[str] = []
    for bind in binds:
        args += ["--bind", bind]
    return args


def _extra_flags() -> list[str]:
    raw = os.getenv("SWE_GAME_BENCH_APPTAINER_FLAGS", "").strip()
    if raw:
        return shlex.split(raw)
    # SWE-agent creates /<repo_name> symlinks and /root tool caches. With a
    # read-only SIF, writable-tmpfs gives those rootfs writes an ephemeral layer.
    return ["--writable-tmpfs"]


def _exec_env() -> dict[str, str]:
    env = os.environ.copy()
    inside = {
        "SWE_GAME_BENCH_DATA": "/pipeline/benchmark",
        "SWE_GAME_BENCH_RUNS": "/pipeline/runs",
        "PYTHONPATH": "/pipeline/src",
        "HOME": "/root",
        "SWE_AGENT_SRC_ROOT": "/opt/SWE-agent",
        "SWEAGENT_CMD": "/opt/swe-agent-venv/bin/python -m sweagent",
        "GITHUB_TOKEN": os.getenv("GITHUB_TOKEN", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
    }
    # Apptainer uses APPTAINERENV_; older Singularity uses SINGULARITYENV_.
    for key, value in inside.items():
        env[f"APPTAINERENV_{key}"] = value
        env[f"SINGULARITYENV_{key}"] = value
    return env


def _base_exec_args(instance: Instance, repo_cfg: RepoConfig) -> list[str]:
    image = image_path(instance, repo_cfg)
    return [
        runtime(),
        "exec",
        *_extra_flags(),
        *_bind_args(repo_cfg, instance.unity_bucket),
        str(image),
    ]


def prepare_instance(instance: Instance, repo_cfg: RepoConfig) -> int:
    """Check that the expected SIF image exists.

    Apptainer execution is intentionally one-shot, so there is no daemon or
    compose service to start here.
    """
    image = image_path(instance, repo_cfg)
    if image.exists():
        print(f"[apptainer] image ready: {image}")
        return 0
    print(f"[apptainer][ERROR] Missing image: {image}")
    print(
        "[apptainer] Set SWE_GAME_BENCH_APPTAINER_IMAGE_DIR or "
        "SWE_GAME_BENCH_APPTAINER_IMAGE, or build/copy the .sif first."
    )
    return 1


def shell(repo_key: str, bucket: str) -> int:
    from .dataset import load_repos

    image = image_path_for(repo_key, bucket)
    if not image.exists():
        print(f"[apptainer][ERROR] Missing image: {image}")
        return 1
    repos = load_repos()
    if repo_key not in repos:
        print(f"[apptainer][ERROR] Unknown repo: {repo_key}")
        return 1
    cmd = [
        runtime(),
        "shell",
        *_extra_flags(),
        *_bind_args(repos[repo_key], bucket),
        str(image),
    ]
    print("CMD:", " ".join(map(str, cmd)))
    return subprocess.run(cmd, env=_exec_env()).returncode


def exec_ephemeral(instance: Instance, repo_cfg: RepoConfig, cli_args: list[str]) -> int:
    """Run the package CLI once inside the SIF image."""
    image = image_path(instance, repo_cfg)
    if not image.exists():
        print(f"[apptainer][ERROR] Missing image: {image}")
        print(
            "[hint] Expected naming is "
            f"{image_dir() / f'swegb-{repo_cfg.key}-{instance.unity_bucket}.sif'}"
        )
        return 1

    inner = (
        "cd /pipeline; "
        "bash /pipeline/benchmark/docker/activate_license.sh > /tmp/license_activation.log 2>&1; "
        "exec /opt/swe-agent-venv/bin/python -u -m swe_game_bench.cli "
        + " ".join(shlex.quote(a) for a in cli_args)
    )
    cmd = [
        *_base_exec_args(instance, repo_cfg),
        "bash",
        "-lc",
        inner,
    ]
    print("CMD:", " ".join(map(str, cmd)))
    return subprocess.run(cmd, env=_exec_env()).returncode


def exec_cli(instance: Instance, repo_cfg: RepoConfig, cli_args: list[str]) -> int:
    """Compatibility alias: Apptainer uses one-shot exec by default."""
    return exec_ephemeral(instance, repo_cfg, cli_args)
