"""Shared git operations: clone, clean checkout, patch apply, oracle-patch generation."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from .dataset import RepoConfig


def _git_env(repo_cfg: RepoConfig, *, skip_lfs_smudge: bool = True) -> dict[str, str]:
    env = os.environ.copy()
    if repo_cfg.git_lfs_skip_smudge and skip_lfs_smudge:
        env["GIT_LFS_SKIP_SMUDGE"] = "1"
    else:
        env.pop("GIT_LFS_SKIP_SMUDGE", None)
    return env


def _default_lfs_url(repo_cfg: RepoConfig) -> str:
    return repo_cfg.repo_url.rstrip("/") + "/info/lfs"


def _looks_like_lfs_pointer(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(128)
    except OSError:
        return False
    return head.startswith(b"version https://git-lfs.github.com/spec/v1")


def run(cmd, cwd=None, check=True, timeout=None, env=None, input=None):
    print("CMD:", " ".join(map(str, cmd)))
    try:
        p = subprocess.run(
            cmd,
            cwd=cwd,
            input=input,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + "\n[HARNESS] TIMEOUT\n"
        print(out)
        if check:
            raise SystemExit(124)
        return 124, out
    print(p.stdout)
    if check and p.returncode != 0:
        raise SystemExit(p.returncode)
    return p.returncode, p.stdout


def _submodule_tracked_at(repo_cfg: RepoConfig, workdir: Path, rel_path: str, rev: str = "HEAD") -> bool:
    _, out = run(["git", "ls-tree", rev, rel_path], cwd=workdir, check=False, env=_git_env(repo_cfg))
    return out.lstrip().startswith("160000 commit")


def _update_submodules(repo_cfg: RepoConfig, workdir: Path) -> None:
    env = _git_env(repo_cfg)
    for rel_path in repo_cfg.submodule_paths:
        if not _submodule_tracked_at(repo_cfg, workdir, rel_path):
            print(f"[submodule] {rel_path} is tracked as a normal tree at this commit; skipping update")
            continue
        run(["git", "submodule", "sync", rel_path], cwd=workdir, check=False, env=env)
        run(["git", "submodule", "update", "--init", "--force", rel_path], cwd=workdir, check=True, env=env)
        sub_dir = workdir / rel_path
        run(["git", "reset", "--hard"], cwd=sub_dir, check=False, env=env)
        run(["git", "clean", "-fdx"], cwd=sub_dir, check=False, env=env)


def _materialize_lfs_paths(repo_cfg: RepoConfig, workdir: Path) -> None:
    if not repo_cfg.git_lfs_include_paths:
        return

    pointer_paths = [
        rel_path
        for rel_path in repo_cfg.git_lfs_include_paths
        if _looks_like_lfs_pointer(workdir / rel_path)
    ]
    if not pointer_paths:
        return

    _, version_out = run(
        ["git", "lfs", "version"],
        cwd=workdir,
        check=False,
        env=_git_env(repo_cfg, skip_lfs_smudge=False),
    )
    if "git-lfs" not in version_out.lower():
        raise RuntimeError(
            f"Repo '{repo_cfg.key}' needs Git LFS files, but 'git lfs' is not available."
        )

    lfs_url = repo_cfg.git_lfs_url or _default_lfs_url(repo_cfg)
    include_arg = ",".join(repo_cfg.git_lfs_include_paths)
    print(f"[lfs] Materializing {len(pointer_paths)} LFS file(s) for {repo_cfg.key}")
    run(["git", "config", "--local", "lfs.url", lfs_url], cwd=workdir, check=True)
    run(
        ["git", "lfs", "pull", "origin", f"--include={include_arg}", "--exclude="],
        cwd=workdir,
        check=True,
        env=_git_env(repo_cfg, skip_lfs_smudge=False),
    )

    remaining = [
        rel_path
        for rel_path in pointer_paths
        if _looks_like_lfs_pointer(workdir / rel_path)
    ]
    if remaining:
        raise RuntimeError(
            f"Git LFS files are still pointers after pull for repo '{repo_cfg.key}': "
            + ", ".join(remaining)
        )


def ensure_repo(repo_cfg: RepoConfig) -> Path:
    workdir = repo_cfg.resolved_workdir()
    env = _git_env(repo_cfg)
    if (workdir / ".git").exists():
        run(["git", "fetch", "--all", "--prune"], cwd=workdir, check=False, env=env)
    else:
        if workdir.exists():
            shutil.rmtree(workdir, ignore_errors=True)
        # Prefer the repo mirror baked into the image (fast, offline); keep
        # origin pointed at the real URL so missing SHAs can still be fetched.
        cache = Path(os.getenv("SWEGB_REPO_CACHE", "/opt/repo-cache.git"))
        if cache.is_dir():
            run(["git", "clone", str(cache), str(workdir)], check=True, env=env)
            run(["git", "remote", "set-url", "origin", repo_cfg.repo_url],
                cwd=workdir, check=True, env=env)
        else:
            run(["git", "clone", repo_cfg.repo_url, str(workdir)], check=True, env=env)
    if repo_cfg.submodule_paths:
        _update_submodules(repo_cfg, workdir)
    return workdir


def fetch_sha(repo_cfg: RepoConfig, sha: str) -> None:
    workdir = repo_cfg.resolved_workdir()
    run(["git", "fetch", "origin", sha], cwd=workdir, check=False, env=_git_env(repo_cfg))


def checkout_clean(repo_cfg: RepoConfig, sha: str) -> None:
    workdir = repo_cfg.resolved_workdir()
    env = _git_env(repo_cfg)
    run(["git", "reset", "--hard"], cwd=workdir, check=False, env=env)
    run(["git", "clean", "-fdx"], cwd=workdir, check=False, env=env)
    # We remove stale submodule checkouts that would otherwise be left behind and cause confusion, since git clean doesn't touch nested repos. We identify them by checking if the submodule path is tracked as a normal tree at the target commit; if so, we skip the removal since it's possible the repo just switched from a nested to a non-nested layout. In that case, the old checkout will be removed on the next run when it's no longer tracked as a normal tree, so we won't accidentally lose any data by skipping it this time.
    for rel_path in repo_cfg.submodule_paths:
        sub_dir = workdir / rel_path
        if not _submodule_tracked_at(repo_cfg, workdir, rel_path, sha) and (sub_dir / ".git").exists():
            print(f"[submodule] Removing stale {rel_path} checkout for embedded-tree commit")
            shutil.rmtree(sub_dir, ignore_errors=True)
    run(["git", "checkout", "-f", sha], cwd=workdir, check=True, env=env)
    _materialize_lfs_paths(repo_cfg, workdir)
    if repo_cfg.submodule_paths:
        _update_submodules(repo_cfg, workdir)


def _try_janoarg_eol_compatible_apply(
    repo_cfg: RepoConfig,
    workdir: Path,
    patch_text: str,
) -> bool:
    """Apply an unchanged JANOARG patch whose only mismatch is CRLF versus LF."""
    if repo_cfg.key != "janoarg":
        return False

    sections = [
        section
        for section in re.split(r"(?=^diff --git )", patch_text, flags=re.MULTILINE)
        if section.startswith("diff --git ")
    ]
    if not sections:
        return False

    workdir_resolved = workdir.resolve()
    targets: list[Path] = []

    for section in sections:
        header = re.search(
            r"^diff --git a/(.+) b/(.+)$",
            section,
            flags=re.MULTILINE,
        )
        index = re.search(
            r"^index ([0-9a-f]+)\.\.[0-9a-f]+(?: \d+)?$",
            section,
            flags=re.MULTILINE,
        )
        old_path = re.search(r"^--- a/(.+)$", section, flags=re.MULTILINE)
        new_path = re.search(r"^\+\+\+ b/(.+)$", section, flags=re.MULTILINE)
        if not header or not index or not old_path or not new_path:
            return False

        rel_paths = {
            header.group(1),
            header.group(2),
            old_path.group(1),
            new_path.group(1),
        }
        if len(rel_paths) != 1:
            return False

        rel_path = rel_paths.pop()
        path_parts = Path(rel_path).parts
        if not path_parts or any(part in {"", ".", ".."} for part in path_parts):
            return False

        target = (workdir / Path(*path_parts)).resolve()
        try:
            target.relative_to(workdir_resolved)
        except ValueError:
            return False
        if not target.is_file():
            return False

        rc, head_blob = run(
            ["git", "rev-parse", f"HEAD:{rel_path}"],
            cwd=workdir,
            check=False,
            env=_git_env(repo_cfg),
        )
        if rc != 0 or not head_blob.strip().startswith(index.group(1)):
            return False

        blob_proc = subprocess.run(
            ["git", "show", f"HEAD:{rel_path}"],
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_git_env(repo_cfg),
        )
        if blob_proc.returncode != 0:
            return False

        current = target.read_bytes()
        base = blob_proc.stdout
        if b"\r\n" not in current:
            return False
        if current.count(b"\n") != current.count(b"\r\n"):
            return False
        if current.replace(b"\r\n", b"\n") != base.replace(b"\r\n", b"\n"):
            return False

        targets.append(target)

    originals = {target: target.read_bytes() for target in targets}
    applied = False
    try:
        for target, data in originals.items():
            target.write_bytes(data.replace(b"\r\n", b"\n"))

        check_cmd = ["git", "apply", "--check", "--whitespace=nowarn", "-"]
        print("CMD:", " ".join(check_cmd))
        check_proc = subprocess.run(
            check_cmd,
            cwd=workdir,
            input=patch_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_git_env(repo_cfg),
        )
        check_out = check_proc.stdout.decode("utf-8", errors="replace")
        print(check_out)
        if check_proc.returncode != 0:
            return False

        apply_cmd = ["git", "apply", "--whitespace=nowarn", "-"]
        print("CMD:", " ".join(apply_cmd))
        apply_proc = subprocess.run(
            apply_cmd,
            cwd=workdir,
            input=patch_text.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=_git_env(repo_cfg),
        )
        apply_out = apply_proc.stdout.decode("utf-8", errors="replace")
        print(apply_out)
        if apply_proc.returncode != 0:
            return False

        for target in targets:
            data = target.read_bytes().replace(b"\r\n", b"\n")
            target.write_bytes(data.replace(b"\n", b"\r\n"))

        applied = True
        return True
    finally:
        if not applied:
            for target, data in originals.items():
                target.write_bytes(data)


def apply_patch(repo_cfg: RepoConfig, patch_path: Path) -> None:
    from . import prepare

    if not patch_path.exists() or patch_path.stat().st_size == 0:
        raise RuntimeError(f"Patch missing or empty: {patch_path}")
    workdir = repo_cfg.resolved_workdir()

    raw = patch_path.read_text(encoding="utf-8", errors="replace")
    patch_text, dropped = prepare.strip_scrubbed_audio_diffs(raw)
    if dropped:
        print(f"[apply] Dropped {len(dropped)} scrubbed-audio artifact diff(s) from patch")
    if not patch_text.strip():
        print("[apply] Patch contained only scrubbed-audio artifacts; nothing to apply")
        return

    # Keep the normal path identical for patches that already apply cleanly.
    rc, _ = run(
        ["git", "apply", "--check", "--whitespace=nowarn", "-"],
        cwd=workdir,
        check=False,
        env=_git_env(repo_cfg),
        input=patch_text,
    )
    if rc == 0:
        run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=workdir,
            check=True,
            env=_git_env(repo_cfg),
            input=patch_text,
        )
        return

    print("[apply] Normal apply failed; checking JANOARG EOL compatibility")
    if _try_janoarg_eol_compatible_apply(repo_cfg, workdir, patch_text):
        print("[apply] Patch applied using JANOARG EOL compatibility fallback")
        return

    raise SystemExit(rc)


def generate_oracle_patch(repo_cfg: RepoConfig, base_sha: str, fix_sha: str, target_files: list[str]) -> str:
    """Diff of the developers' real fix, restricted to the instance's target files."""
    workdir = ensure_repo(repo_cfg)
    env = _git_env(repo_cfg)
    run(["git", "fetch", "origin", base_sha], cwd=workdir, check=False, env=env)
    run(["git", "fetch", "origin", fix_sha], cwd=workdir, check=False, env=env)
    cmd = ["git", "diff", f"{base_sha}..{fix_sha}", "--", *target_files]
    _, diff = run(cmd, cwd=workdir, check=True, env=env)
    if not diff.strip():
        raise RuntimeError(
            f"Oracle patch is empty for target files: {target_files} "
            f"({base_sha[:10]}..{fix_sha[:10]})"
        )
    return diff
