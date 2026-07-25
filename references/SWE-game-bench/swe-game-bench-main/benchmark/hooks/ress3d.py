"""RE-SS3D/SS3D-specific source surgery (ported from the original swe_evaluator)."""

import re
from pathlib import Path


def scrub_fishnet_prefab_generator(workdir: Path, **_) -> None:
    """Avoid a Linux batchmode import crash from FishNet's editor prefab generator."""
    (workdir / "Assets" / "Content" / "Data").mkdir(parents=True, exist_ok=True)

    bad_path = r"Assets\Content\Data\DefaultPrefabObjects.asset"
    good_path = "Assets/Content/Data/DefaultPrefabObjects.asset"
    for p in workdir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".asset", ".json", ".txt", ".cs"}:
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if bad_path in txt:
            print(f"[scrub_fishnet] Normalizing prefab path in {p.relative_to(workdir)}")
            p.write_text(txt.replace(bad_path, good_path), encoding="utf-8")

    generator = (
        workdir / "Assets" / "Scripts" / "External" / "FishNet" / "Runtime"
        / "Editor" / "PrefabCollectionGenerator" / "Generator.cs"
    )
    if not generator.exists():
        return
    try:
        txt = generator.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return

    txt2 = txt.replace(
        "string assetPath = settings.AssetPath;",
        "string assetPath = settings.AssetPath.Replace('\\\\', '/');",
        1,
    )
    for var_name in ("path", "directory"):
        pattern = rf"^(\s*)Directory\.CreateDirectory\({var_name}\);"

        def guard(match, name=var_name):
            indent = match.group(1)
            return f"{indent}if (!string.IsNullOrEmpty({name}))\n{indent}    Directory.CreateDirectory({name});"

        txt2 = re.sub(pattern, guard, txt2, count=1, flags=re.MULTILINE)
    if txt2 != txt:
        print("[scrub_fishnet] Guarding empty prefab directory path")
        generator.write_text(txt2, encoding="utf-8")
