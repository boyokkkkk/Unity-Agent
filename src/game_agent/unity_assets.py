from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any


GUID_PATTERN = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
REFERENCE_PATTERN = re.compile(r"\bguid:\s*([0-9a-fA-F]{32})\b")
YAML_EXTENSIONS = {".unity", ".prefab", ".asset", ".mat", ".controller", ".anim"}
IGNORED_NAMES = {".git", "library", "temp", "logs", "obj", "build", "builds", "usersettings"}


def audit_unity_assets(project_path: Path) -> dict[str, Any]:
    """Audit Unity metadata and YAML references without modifying the project."""
    assets = project_path / "Assets"
    if not assets.is_dir():
        return {
            "status": "failed",
            "errors": [{"code": "assets_missing", "path": "Assets"}],
            "warnings": [],
            "stats": {"assets": 0, "meta_files": 0, "yaml_files": 0},
        }

    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    guid_paths: dict[str, list[str]] = defaultdict(list)
    asset_count = 0
    meta_count = 0
    yaml_files: list[Path] = []

    for path in assets.rglob("*"):
        relative = path.relative_to(project_path).as_posix()
        if any(part.casefold() in IGNORED_NAMES for part in Path(relative).parts):
            continue
        if path.suffix.casefold() == ".meta":
            meta_count += 1
            target = path.with_suffix("")
            if not target.exists():
                errors.append({"code": "orphan_meta", "path": relative})
            text = path.read_text(encoding="utf-8", errors="replace")
            match = GUID_PATTERN.search(text)
            if not match:
                errors.append({"code": "missing_guid", "path": relative})
            else:
                guid_paths[match.group(1).casefold()].append(relative)
            continue
        asset_count += 1
        if not Path(str(path) + ".meta").is_file():
            errors.append({"code": "missing_meta", "path": relative})
        if path.is_file() and path.suffix.casefold() in YAML_EXTENSIONS:
            yaml_files.append(path)

    for guid, paths in sorted(guid_paths.items()):
        if len(paths) > 1:
            errors.append({"code": "duplicate_guid", "path": ", ".join(paths), "guid": guid})

    known_guids = set(guid_paths)
    for path in yaml_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = path.relative_to(project_path).as_posix()
        if not text.lstrip().startswith("%YAML") or "--- !u!" not in text:
            errors.append({"code": "invalid_unity_yaml", "path": relative})
            continue
        for guid in sorted(set(REFERENCE_PATTERN.findall(text))):
            normalized = guid.casefold()
            if normalized != "0" * 32 and normalized not in known_guids:
                warnings.append({"code": "unresolved_guid", "path": relative, "guid": normalized})

    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "stats": {"assets": asset_count, "meta_files": meta_count, "yaml_files": len(yaml_files)},
    }
