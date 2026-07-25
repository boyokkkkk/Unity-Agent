"""Load benchmark instances (instances.json) and per-repo configuration (repos.yaml)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import paths

StepSpec = "str | dict"  #


@dataclass
class UnityBucket:
    name: str
    image_tag: str


@dataclass
class RepoConfig:
    key: str                       # short repo key, e.g. "fungus"
    gh_repo: str                   # e.g. "snozbot/fungus"
    repo_url: str
    workdir: str                   # checkout location inside the container
    default_unity_bucket: str
    unity_buckets: dict[str, UnityBucket]
    prepare_steps: list = field(default_factory=list)
    hooks_module: str | None = None
    git_lfs_skip_smudge: bool = False
    git_lfs_include_paths: list[str] = field(default_factory=list)
    git_lfs_url: str | None = None
    main_asmdef: dict | None = None   # {match_names, fallback_name, fallback_path, optional}
    submodule_paths: list = field(default_factory=list)

    def resolved_workdir(self) -> Path:
        env = os.getenv("WORKDIR", "").strip()
        if env:
            return Path(env)
        if os.name == "nt":
            return Path("C:/tmp") / Path(self.workdir).name
        return Path(self.workdir)


@dataclass
class Instance:
    instance_id: str               # e.g. "fungus-879"
    repo: str                      # repo key into repos.yaml
    issue_number: int
    issue_url: str
    base_sha: str
    fix_sha: str
    target_files: list[str]
    test_class: str
    test_platform: str             # EditMode | PlayMode
    unity_bucket: str
    project_subdir: str | None = None   # Unity project root relative to the checkout
    extra_prepare_steps: list = field(default_factory=list)
    post_patch_steps: list = field(default_factory=list)
    test_suites: list[dict] = field(default_factory=list)
    benchmark_set: str = "core"

    @property
    def issue_file(self) -> Path:
        return paths.issues_dir() / f"{self.instance_id}.txt"

    @property
    def tests_tree(self) -> Path:
        return paths.tests_dir() / self.instance_id

    @property
    def oracle_patch_file(self) -> Path:
        return paths.oracle_patches_dir() / f"{self.instance_id}.patch"

    def default_outdir(self) -> Path:
        return paths.runs_root() / self.instance_id


def load_repos() -> dict[str, RepoConfig]:
    raw = yaml.safe_load(paths.repos_path().read_text(encoding="utf-8"))
    repos: dict[str, RepoConfig] = {}
    for key, cfg in raw["repos"].items():
        buckets = {
            name: UnityBucket(name=name, image_tag=b["image_tag"])
            for name, b in cfg["unity_buckets"].items()
        }
        repos[key] = RepoConfig(
            key=key,
            gh_repo=cfg["gh_repo"],
            repo_url=cfg["repo_url"],
            workdir=cfg["workdir"],
            default_unity_bucket=cfg["default_unity_bucket"],
            unity_buckets=buckets,
            prepare_steps=cfg.get("prepare_steps", []),
            hooks_module=cfg.get("hooks_module"),
            git_lfs_skip_smudge=bool(cfg.get("git_lfs_skip_smudge", False)),
            git_lfs_include_paths=list(cfg.get("git_lfs_include_paths", [])),
            git_lfs_url=cfg.get("git_lfs_url"),
            main_asmdef=cfg.get("main_asmdef"),
            submodule_paths=list(cfg.get("submodule_paths", [])),
        )
    return repos


def load_instances() -> list[Instance]:
    raw = json.loads(paths.instances_path().read_text(encoding="utf-8"))
    out: list[Instance] = []
    for entry in raw:
        out.append(
            Instance(
                instance_id=entry["instance_id"],
                repo=entry["repo"],
                issue_number=int(entry["issue_number"]),
                issue_url=entry.get("issue_url", ""),
                base_sha=entry["base_sha"],
                fix_sha=entry["fix_sha"],
                target_files=list(entry.get("target_files", [])),
                test_class=entry["test_class"],
                test_platform=entry["test_platform"],
                unity_bucket=entry["unity_bucket"],
                project_subdir=entry.get("project_subdir"),
                extra_prepare_steps=entry.get("extra_prepare_steps", []),
                post_patch_steps=entry.get("post_patch_steps", []),
                test_suites=list(entry.get("test_suites", [])),
                benchmark_set=str(entry.get("benchmark_set", "core")),
            )
        )
    return out


def get_instance(instance_id: str) -> Instance:
    for inst in load_instances():
        if inst.instance_id == instance_id:
            return inst
    raise KeyError(
        f"Instance '{instance_id}' not found in {paths.instances_path()}. "
        "Run 'swe-game-bench list' to see available instances."
    )


def get_repo(repo_key: str) -> RepoConfig:
    repos = load_repos()
    if repo_key not in repos:
        raise KeyError(f"Repo '{repo_key}' not found in {paths.repos_path()}")
    return repos[repo_key]
