"""Repo preparation steps (scrubs) that make old Unity projects compile headlessly.

A step spec is either a builtin step name (string) or a dict:
    {"name": "<builtin or 'hook'>", ...params}
Hook steps dispatch to a function in benchmark/hooks/<repo.hooks_module>.py, which
receives the checkout directory as its only argument. Hooks hold repo-specific
source surgery that does not generalize (e.g. AoTTG's URP scrubs).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

from . import paths
from .dataset import RepoConfig


# Extensions deleted by scrub_audio. Shared with strip_scrubbed_audio_diffs so the
# patch filter always tracks whatever scrub_audio removes.
SCRUBBED_AUDIO_EXTS = (".mp3", ".wav", ".ogg")


def scrub_audio(workdir: Path, **_) -> None:
    """Delete audio assets; they slow imports and some corrupt files crash the import pipeline."""
    for ext in SCRUBBED_AUDIO_EXTS:
        for p in workdir.rglob("*" + ext):
            try:
                p.unlink()
            except Exception:
                pass


def remove_paths(workdir: Path, paths: list[str] | None = None, **_) -> None:
    """Remove instance-irrelevant files that otherwise break the pinned checkout."""
    root = workdir.resolve()
    for rel_path in paths or []:
        candidate = (workdir / rel_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"remove_paths target escapes the project: {rel_path}") from exc
        if candidate.is_dir() and not candidate.is_symlink():
            shutil.rmtree(candidate)
            print(f"[remove_paths] Removed directory: {rel_path}")
        elif candidate.exists() or candidate.is_symlink():
            candidate.unlink()
            print(f"[remove_paths] Removed file: {rel_path}")


def strip_scrubbed_audio_diffs(patch_text: str) -> tuple[str, list[str]]:
    """Remove diff sections that target scrubbed audio assets (and their .meta companions).

    Patch generators (e.g. SWE-agent) build their diff with ``git diff`` inside a
    container where scrub_audio has already deleted the audio files, so the patch
    carries deletion hunks for every one of them. At evaluate time the audio is
    scrubbed again, so ``git apply`` fails with "No such file or directory" on those
    hunks and -- because git apply is atomic -- aborts the whole patch, dropping the
    real code fix and recording a spurious FAIL. These hunks are scrub artifacts,
    never part of a genuine fix, so we drop them before applying.

    Returns the filtered patch text and the list of dropped target paths.
    """
    lines = patch_text.splitlines(keepends=True)
    kept: list[str] = []
    dropped: list[str] = []
    skip = False
    for line in lines:
        if line.startswith("diff --git "):
            target = line.rstrip("\r\n")
            low = target.lower()
            skip = any(
                low.endswith(ext) or low.endswith(ext + ".meta")
                for ext in SCRUBBED_AUDIO_EXTS
            )
            if skip:
                dropped.append(target.split(" b/", 1)[-1])
                continue
        if not skip:
            kept.append(line)
    return "".join(kept), dropped


def scrub_asmdef_platforms(workdir: Path, blocked_platforms: list[str] | None = None, **_) -> None:
    """Remove platform names Unity no longer recognizes (e.g. 'BJM') from .asmdef files."""
    blocked = {str(x).strip() for x in (blocked_platforms or ["BJM"])}
    for p in workdir.rglob("*.asmdef"):
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        s = txt.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            changed = False
            for k in ("includePlatforms", "excludePlatforms"):
                if isinstance(obj.get(k), list):
                    before = len(obj[k])
                    obj[k] = [x for x in obj[k] if str(x).strip() not in blocked]
                    if len(obj[k]) != before:
                        changed = True
            if changed:
                try:
                    p.write_text(json.dumps(obj, indent=4, sort_keys=True) + "\n", encoding="utf-8")
                except Exception:
                    pass
        else:
            txt2 = txt
            for name in blocked:
                txt2 = re.sub(r'(\s*)"' + re.escape(name) + r'"\s*,?\s*', r"\1", txt2)
            txt2 = re.sub(r",\s*]", "]", txt2)
            txt2 = re.sub(r",\s*}", "}", txt2)
            if txt2 != txt:
                try:
                    p.write_text(txt2 + ("" if txt2.endswith("\n") else "\n"), encoding="utf-8")
                except Exception:
                    pass


def scrub_manifest_packages(
    workdir: Path,
    blocked_packages: list[str] | None = None,
    blocked_package_substrings: list[str] | None = None,
    blocked_registry_hosts: list[str] | None = None,
    blocked_asmdef_refs: list[str] | None = None,
    **_,
) -> None:
    """Drop UPM packages, scoped registries, and asmdef references that do not
    resolve in the pinned editor (or point at unreachable registries)."""
    manifest_path = workdir / "Packages" / "manifest.json"
    blocked_pkgs = set(blocked_packages or [])
    blocked_subs = [s.lower() for s in (blocked_package_substrings or [])]
    blocked_hosts = list(blocked_registry_hosts or [])
    if (blocked_pkgs or blocked_subs or blocked_hosts) and manifest_path.exists():
        try:
            obj = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            obj = None
        if isinstance(obj, dict):
            deps = obj.get("dependencies", {})
            changed = False
            for pkg in list(deps.keys()):
                if pkg in blocked_pkgs or any(s in pkg.lower() for s in blocked_subs):
                    print(f"[scrub_manifest] Removing blocked package: {pkg}")
                    del deps[pkg]
                    changed = True
            if blocked_hosts and isinstance(obj.get("scopedRegistries"), list):
                kept = []
                for reg in obj["scopedRegistries"]:
                    url = str(reg.get("url", ""))
                    if any(host in url for host in blocked_hosts):
                        print(f"[scrub_manifest] Dropping scopedRegistry: {url}")
                        changed = True
                        continue
                    kept.append(reg)
                obj["scopedRegistries"] = kept
            if changed:
                obj["dependencies"] = deps
                manifest_path.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")

    blocked_refs = {str(x).strip() for x in (blocked_asmdef_refs or [])}
    if not blocked_refs:
        return
    for asmdef_path in workdir.rglob("*.asmdef"):
        try:
            asmdef = json.loads(asmdef_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        refs = asmdef.get("references")
        if not isinstance(refs, list):
            continue
        before = len(refs)
        asmdef["references"] = [r for r in refs if str(r).strip() not in blocked_refs]
        if len(asmdef["references"]) != before:
            print(f"[scrub_asmdef] Removing blocked reference(s) from {asmdef_path}")
            asmdef_path.write_text(json.dumps(asmdef, indent=4, sort_keys=True) + "\n", encoding="utf-8")


BUILTIN_STEPS = {
    "remove_paths": remove_paths,
    "scrub_audio": scrub_audio,
    "scrub_asmdef_platforms": scrub_asmdef_platforms,
    "scrub_manifest_packages": scrub_manifest_packages,
}

_hook_modules: dict[str, object] = {}


def _load_hooks(module_name: str):
    if module_name in _hook_modules:
        return _hook_modules[module_name]
    hook_path = paths.hooks_dir() / f"{module_name}.py"
    if not hook_path.exists():
        raise FileNotFoundError(f"Hooks module not found: {hook_path}")
    spec = importlib.util.spec_from_file_location(f"swe_game_bench_hooks_{module_name}", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _hook_modules[module_name] = mod
    return mod


def run_steps(repo_cfg: RepoConfig, steps: list, workdir: Path) -> None:
    for spec in steps:
        if isinstance(spec, str):
            name, params = spec, {}
        else:
            params = dict(spec)
            name = params.pop("name")

        if name == "hook":
            func_name = params.pop("func")
            if not repo_cfg.hooks_module:
                raise ValueError(f"Repo '{repo_cfg.key}' has hook step '{func_name}' but no hooks_module configured")
            mod = _load_hooks(repo_cfg.hooks_module)
            print(f"[prepare] hook: {repo_cfg.hooks_module}.{func_name}")
            getattr(mod, func_name)(workdir, **params)
        elif name in BUILTIN_STEPS:
            print(f"[prepare] {name}")
            BUILTIN_STEPS[name](workdir, **params)
        else:
            raise ValueError(f"Unknown prepare step '{name}' for repo '{repo_cfg.key}'")
