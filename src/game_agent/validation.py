from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from game_agent.processes import terminate_process_tree
from game_agent.unity_assets import audit_unity_assets


VALIDATION_SCHEMA_VERSION = "game-agent-unity-validation-v1"


def find_unity_editor(project_path: Path, configured_path: str = "") -> Path | None:
    candidates = [configured_path, os.getenv("UNITY_EDITOR_PATH", "")]
    version_file = project_path / "ProjectSettings" / "ProjectVersion.txt"
    version = ""
    if version_file.is_file():
        match = re.search(r"m_EditorVersion:\s*([^\s]+)", version_file.read_text(encoding="utf-8", errors="replace"))
        version = match.group(1) if match else ""
    if version and os.name == "nt":
        candidates.append(f"C:/Program Files/Unity/Hub/Editor/{version}/Editor/Unity.exe")
    discovered = shutil.which("Unity.exe") or shutil.which("Unity")
    if discovered:
        candidates.append(discovered)
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def _run_process(arguments: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        arguments, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process.pid)
        output, _ = process.communicate()
        raise subprocess.TimeoutExpired(arguments, timeout, output=output)
    return subprocess.CompletedProcess(arguments, process.returncode, stdout=output)


class UnityValidator:
    def __init__(
        self,
        project_path: Path,
        artifact_dir: Path,
        config: dict[str, Any] | None = None,
        *,
        event_sink: Callable[..., object] | None = None,
        runner: Callable[[list[str], int], subprocess.CompletedProcess[str]] = _run_process,
    ) -> None:
        self.project_path = project_path.resolve()
        self.artifact_dir = artifact_dir.resolve()
        self.config = dict(config or {})
        self.event_sink = event_sink
        self.runner = runner

    def _emit(self, event: str, **data: Any) -> None:
        if self.event_sink:
            self.event_sink(event, component="environment", **data)

    def run(self) -> dict[str, Any]:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        checks: list[dict[str, Any]] = []
        started = time.perf_counter()
        checks.append({"name": "asset_integrity", **audit_unity_assets(self.project_path)})
        modes = list(self.config.get("modes", ["compile", "editmode", "playmode"]))
        editor = find_unity_editor(self.project_path, str(self.config.get("editor_path", "")))
        for mode in modes:
            checks.append(self._run_editor_check(mode, editor))
        statuses = {check["status"] for check in checks}
        overall = "failed" if "failed" in statuses or "timed_out" in statuses else (
            "passed" if statuses == {"passed"} else "skipped_unavailable"
        )
        summary = {
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "project_path": str(self.project_path),
            "unity_editor": str(editor) if editor else "",
            "status": overall,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "checks": checks,
        }
        (self.artifact_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        return summary

    def _run_editor_check(self, mode: str, editor: Path | None) -> dict[str, Any]:
        if mode not in {"compile", "editmode", "playmode"}:
            return {"name": mode, "status": "failed", "error": "unknown validation mode"}
        if editor is None:
            result = {"name": mode, "status": "skipped_unavailable", "reason": "Unity Editor not found"}
            self._emit("validation_end", validation=mode, **result)
            return result
        timeout = int(self.config.get("timeout_seconds", 1200))
        log_path = self.artifact_dir / f"{mode}.log"
        arguments = [str(editor), "-batchmode", "-quit", "-projectPath", str(self.project_path), "-logFile", str(log_path)]
        result_path: Path | None = None
        if mode != "compile":
            platform = "EditMode" if mode == "editmode" else "PlayMode"
            result_path = self.artifact_dir / f"{mode}-results.xml"
            arguments += ["-runTests", "-testPlatform", platform, "-testResults", str(result_path)]
        self._emit("validation_start", validation=mode, command=arguments, timeout_seconds=timeout)
        started = time.perf_counter()
        try:
            completed = self.runner(arguments, timeout)
            status = "passed" if completed.returncode == 0 else "failed"
            if completed.stdout and not log_path.exists():
                log_path.write_text(completed.stdout, encoding="utf-8")
            result = {
                "name": mode, "status": status, "returncode": completed.returncode,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "log": log_path.name,
            }
            if result_path is not None:
                result["results"] = result_path.name
                if status == "passed" and not result_path.is_file():
                    result.update(status="failed", error="Unity did not produce a test result XML")
                elif status == "passed":
                    try:
                        test_run = ET.parse(result_path).getroot()
                        failed = int(test_run.attrib.get("failed", "0"))
                        if test_run.attrib.get("result", "").casefold() == "failed" or failed > 0:
                            result.update(status="failed", failed_tests=failed, error="Unity tests failed")
                    except (ET.ParseError, ValueError) as exc:
                        result.update(status="failed", error=f"Invalid Unity test result XML: {exc}")
            log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.is_file() else ""
            if status == "passed" and re.search(
                r"(?:error CS\d{4}|scripts have compiler errors|compilation failed)", log_text, re.IGNORECASE
            ):
                result.update(status="failed", error="Unity log contains compiler errors")
        except subprocess.TimeoutExpired as exc:
            if exc.output and not log_path.exists():
                log_path.write_text(str(exc.output), encoding="utf-8")
            result = {
                "name": mode, "status": "timed_out", "duration_ms": int((time.perf_counter() - started) * 1000),
                "timeout_seconds": timeout, "log": log_path.name,
            }
        self._emit("validation_end", validation=mode, **result)
        return result
