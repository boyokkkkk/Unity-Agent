"""AoTTG-2 repo-specific source surgery that does not generalize to other repos.

Each function takes the checkout directory and is referenced from
instances.json / repos.yaml via {"name": "hook", "func": "<function name>"}.
Ported verbatim from Candidates/Aottg/swe_evaluator.py.
"""

import re
from pathlib import Path


def _remove_csharp_method(text: str, signature: str) -> str:
    start = text.find(signature)
    if start == -1:
        return text
    line_start = text.rfind("\n", 0, start) + 1
    brace_start = text.find("{", start)
    if brace_start == -1:
        return text
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                if end < len(text) and text[end] == "\r":
                    end += 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return text[:line_start] + text[end:]
    return text


def scrub_urp_only_source(workdir: Path) -> None:
    """Strip URP-only calls that do not compile on the pinned Unity 2020.1 editor."""
    day_night_path = workdir / "Assets" / "Scripts" / "DayNightCycle" / "DayAndNightControl.cs"
    if day_night_path.exists():
        text = day_night_path.read_text(encoding="utf-8", errors="replace")
        patched = text.replace("using UnityEngine.Rendering.Universal;\n", "")
        patched = patched.replace(
            "                var moonCameraData = MoonCamera.GetUniversalAdditionalCameraData();\n"
            "                moonCameraData.cameraStack.Add(MainCamera);\n",
            "                // Compatibility scrub for this benchmark runner: URP 10.3.1 does not compile on Unity 2020.1.\n",
        )
        if patched != text:
            print("[scrub_source] Removing URP-only camera stack calls from DayAndNightControl.cs")
            day_night_path.write_text(patched, encoding="utf-8")

    quality_path = workdir / "Assets" / "Scripts" / "UI" / "Menu" / "QualityAdaptator.cs"
    if quality_path.exists():
        text = quality_path.read_text(encoding="utf-8", errors="replace")
        patched = text.replace("using UnityEngine.Rendering.Universal;\n", "")
        patched = re.sub(r"\s*private Volume postProcess;\n", "\n", patched)
        patched = _remove_csharp_method(patched, "private void recalculatePostRenderEffects()")
        patched = patched.replace("\n                    this.recalculatePostRenderEffects();", "")
        patched = re.sub(
            r"\n\s*this\.postProcess = GameObject\.FindObjectOfType<Volume>\(\);\n",
            "\n",
            patched,
        )
        if patched != text:
            print("[scrub_source] Removing URP-only post-processing calls from QualityAdaptator.cs")
            quality_path.write_text(patched, encoding="utf-8")


def make_chat_public(workdir: Path) -> None:
    """Widen FengGameManagerMKII.Chat visibility so the injected test can invoke it."""
    fgm_path = workdir / "Assets" / "Scripts" / "FengGameManagerMKII.cs"
    if not fgm_path.exists():
        return
    txt = fgm_path.read_text(encoding="utf-8", errors="replace")
    patched = re.sub(
        r"\b(private|protected|internal)(\s+void\s+Chat\s*\()",
        r"public\2",
        txt,
    )
    if patched != txt:
        fgm_path.write_text(patched, encoding="utf-8")
        print("[surgery] Made FengGameManagerMKII.Chat public")
