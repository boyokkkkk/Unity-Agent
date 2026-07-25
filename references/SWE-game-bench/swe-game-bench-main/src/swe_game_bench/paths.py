"""Locate the benchmark data directory and standard output locations.

Resolution order for the data root:
  1. SWE_GAME_BENCH_DATA environment variable
  2. ./benchmark relative to the current working directory
  3. <repo root>/benchmark relative to this file (editable install from the repo)
"""

import os
from pathlib import Path


def data_root() -> Path:
    env = os.getenv("SWE_GAME_BENCH_DATA", "").strip()
    if env:
        root = Path(env)
        if not root.is_dir():
            raise FileNotFoundError(f"SWE_GAME_BENCH_DATA points to a missing directory: {root}")
        return root

    cwd_candidate = Path.cwd() / "benchmark"
    if (cwd_candidate / "instances.json").exists():
        return cwd_candidate

    repo_candidate = Path(__file__).resolve().parents[2] / "benchmark"
    if (repo_candidate / "instances.json").exists():
        return repo_candidate

    raise FileNotFoundError(
        "Could not locate the benchmark data directory. "
        "Set SWE_GAME_BENCH_DATA or run from the swe-game-bench repository root."
    )


def instances_path() -> Path:
    return data_root() / "instances.json"


def repos_path() -> Path:
    return data_root() / "repos.yaml"


def issues_dir() -> Path:
    return data_root() / "issues"


def tests_dir() -> Path:
    return data_root() / "tests"


def oracle_patches_dir() -> Path:
    return data_root() / "oracle_patches"


def hooks_dir() -> Path:
    return data_root() / "hooks"


def configs_dir() -> Path:
    return data_root() / "configs"


def docker_dir() -> Path:
    return data_root() / "docker"


def runs_root() -> Path:
    """Where evaluation artifacts are written. Defaults to <data root parent>/runs."""
    env = os.getenv("SWE_GAME_BENCH_RUNS", "").strip()
    if env:
        return Path(env)
    return data_root().parent / "runs"
