"""Copy an instance's test tree (benchmark/tests/<instance_id>/) into the checkout.

Test trees are plain files mirroring their in-repo locations (e.g.
Assets/InjectedPRTests/Editor/FooTests.cs). One templating feature exists:
the token __MAIN_ASMDEF__ inside .asmdef files is replaced at inject time with
the repo's main assembly-definition name, resolved against the *checked-out*
commit (asmdef layouts vary across a repo's history). If no matching asmdef
exists at that commit, a fallback auto-referenced asmdef is generated, exactly
mirroring the behavior of the original per-repo evaluators.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .dataset import Instance, RepoConfig

MAIN_ASMDEF_TOKEN = "__MAIN_ASMDEF__"


def _asmdef_names(workdir: Path) -> set[str]:
    names: set[str] = set()
    for p in workdir.rglob("*.asmdef"):
        try:
            obj = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            n = obj.get("name")
            if isinstance(n, str) and n.strip():
                names.add(n.strip())
        except Exception:
            pass
    return names


def resolve_main_asmdef(repo_cfg: RepoConfig, workdir: Path) -> str:
    """Pick the repo's main asmdef name, or generate the configured fallback."""
    cfg = repo_cfg.main_asmdef or {}
    match_names = [str(x) for x in cfg.get("match_names", [])]
    names = _asmdef_names(workdir)

    for wanted in match_names:
        if wanted in names:
            return wanted
    for wanted in match_names:
        for n in names:
            if n.lower() == wanted.lower():
                return n
    for wanted in match_names:
        for n in names:
            if wanted.lower() in n.lower() and "test" not in n.lower():
                return n

    fallback_name = cfg.get("fallback_name")
    fallback_path = cfg.get("fallback_path")
    if not fallback_name or not fallback_path:
        if cfg.get("optional"):
            return None
        raise RuntimeError(
            f"Could not resolve main asmdef for repo '{repo_cfg.key}' and no fallback is configured."
        )
    fp = workdir / fallback_path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        json.dumps(
            {
                "name": fallback_name,
                "references": [],
                "includePlatforms": [],
                "excludePlatforms": [],
                "autoReferenced": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[inject] No main asmdef at this commit; generated fallback: {fallback_path}")
    return fallback_name


def inject_tests(instance: Instance, repo_cfg: RepoConfig, workdir: Path) -> list[Path]:
    """Copy the instance's test tree into workdir. Returns the written paths."""
    src_root = instance.tests_tree
    if not src_root.is_dir():
        raise FileNotFoundError(
            f"Missing test tree for {instance.instance_id}: {src_root}"
        )

    resolved_asmdef: str | None = None
    resolution_done = False
    written: list[Path] = []
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        dst = workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        if src.suffix == ".asmdef":
            text = src.read_text(encoding="utf-8")
            if MAIN_ASMDEF_TOKEN in text:
                if not resolution_done:
                    resolved_asmdef = resolve_main_asmdef(repo_cfg, workdir)
                    resolution_done = True
                if resolved_asmdef:
                    text = text.replace(MAIN_ASMDEF_TOKEN, resolved_asmdef)
                else:
                    # Optional reference and no matching assembly at this commit.
                    obj = json.loads(text)
                    if isinstance(obj.get("references"), list):
                        obj["references"] = [r for r in obj["references"] if r != MAIN_ASMDEF_TOKEN]
                    text = json.dumps(obj, indent=2) + "\n"
                    print(f"[inject] Main asmdef absent at this commit; dropped optional reference in {rel}")
            dst.write_text(text, encoding="utf-8")
        else:
            shutil.copyfile(src, dst)
        written.append(dst)

    if not written:
        raise RuntimeError(f"Test tree for {instance.instance_id} is empty: {src_root}")
    print(f"[inject] {len(written)} file(s) injected for {instance.instance_id}")
    return written
