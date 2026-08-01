from __future__ import annotations

import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


UNITY_GENERATED_DIRS = {".git", "library", "temp", "logs", "obj", "build", "builds", "usersettings"}


def _remove_tree(path: Path) -> None:
    def make_writable(function, target: str, _error) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onerror=make_writable)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=False,
    )


@dataclass
class WorkspaceLease:
    source_project: Path
    project_path: Path
    workspace_root: Path
    mode: str
    repository_root: Path | None = None

    def close(self) -> None:
        if self.mode == "in_place":
            return
        if self.mode == "git_worktree" and self.repository_root is not None:
            _git(self.repository_root, "worktree", "remove", "--force", str(self.workspace_root))
            _git(self.repository_root, "worktree", "prune")
        if self.workspace_root.exists():
            _remove_tree(self.workspace_root)

    def __enter__(self) -> "WorkspaceLease":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _copy_project(source: Path, destination: Path) -> None:
    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name.casefold() in UNITY_GENERATED_DIRS}

    shutil.copytree(source, destination, ignore=ignore)
    initialized = _git(destination, "init")
    if initialized.returncode != 0:
        raise RuntimeError(initialized.stderr.strip() or "Unable to initialize isolated workspace")


def _overlay_dirty_repository(source_root: Path, destination_root: Path) -> None:
    patch = _git(source_root, "diff", "HEAD", "--binary", "--no-ext-diff")
    if patch.returncode != 0:
        raise RuntimeError(patch.stderr.strip() or "Unable to capture dirty workspace")
    if patch.stdout:
        applied = subprocess.run(
            ["git", "apply", "--binary", "--whitespace=nowarn", "-"],
            cwd=destination_root, input=patch.stdout, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        if applied.returncode != 0:
            raise RuntimeError(applied.stderr.strip() or "Unable to overlay dirty workspace")
    untracked = _git(source_root, "ls-files", "--others", "--exclude-standard", "-z")
    if untracked.returncode != 0:
        raise RuntimeError(untracked.stderr.strip() or "Unable to list untracked workspace files")
    for raw_name in filter(None, untracked.stdout.split("\0")):
        source = source_root / raw_name
        destination = destination_root / raw_name
        if any(part.casefold() in UNITY_GENERATED_DIRS for part in Path(raw_name).parts):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def create_task_workspace(source_project: Path, root: Path, *, mode: str = "in_place") -> WorkspaceLease:
    """Create an isolated Unity workspace, preserving tracked, dirty, and untracked inputs."""
    source_project = source_project.resolve()
    if mode == "in_place":
        return WorkspaceLease(source_project, source_project, source_project, mode)
    if mode not in {"auto", "git_worktree", "copy"}:
        raise ValueError(f"Unknown workspace isolation mode: {mode}")
    root = root.resolve()
    if root == source_project or source_project in root.parents:
        raise ValueError("Isolated workspace root must be outside the source Unity project")
    if root.exists():
        raise FileExistsError(f"Workspace already exists: {root}")
    root.parent.mkdir(parents=True, exist_ok=True)

    top = _git(source_project, "rev-parse", "--show-toplevel")
    has_head = _git(source_project, "rev-parse", "--verify", "HEAD").returncode == 0
    if mode != "copy" and top.returncode == 0 and has_head:
        prefix = _git(source_project, "rev-parse", "--show-prefix")
        if prefix.returncode != 0:
            raise RuntimeError(prefix.stderr.strip() or "Unable to locate Unity project inside repository")
        project_relative = Path(prefix.stdout.strip().replace("/", os.sep))
        repository_root = source_project
        for _part in project_relative.parts:
            repository_root = repository_root.parent
        created = _git(repository_root, "worktree", "add", "--detach", str(root), "HEAD")
        if created.returncode != 0:
            raise RuntimeError(created.stderr.strip() or "Unable to create Git worktree")
        try:
            _overlay_dirty_repository(repository_root, root)
        except BaseException:
            _git(repository_root, "worktree", "remove", "--force", str(root))
            raise
        return WorkspaceLease(source_project, root / project_relative, root, "git_worktree", repository_root)

    _copy_project(source_project, root)
    return WorkspaceLease(source_project, root, root, "copy")
