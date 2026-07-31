from __future__ import annotations

import hashlib
import importlib.resources
import json
import shutil
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from game_agent.validation import UnityValidator, _run_process, find_unity_editor

from .schemas import CONTROL_TOOL_NAMES, MUTATION_TOOL_NAMES


class AciConfig(BaseModel):
    """Execution policy for typed Unity mutations."""

    enabled: bool = True
    typed_mutations_enabled: bool = True
    dynamic_tool_exposure_enabled: bool = True
    editor_path: str = ""
    timeout_seconds: int = Field(default=1200, ge=1)
    require_location_evidence: bool = True
    require_target_read: bool = True
    required_validation_modes: list[str] = Field(
        default_factory=lambda: ["editmode", "playmode"],
    )


class UnityMutationExecutor:
    """Execute checkpointed Unity mutations through deterministic local backends."""

    def __init__(
        self,
        *,
        project_root: Path,
        artifact_root: Path | None,
        config: AciConfig | dict[str, Any] | None = None,
        runner: Callable = _run_process,
        validator_factory: Callable[..., UnityValidator] = UnityValidator,
    ) -> None:
        self.project_root = project_root.resolve()
        self.artifact_root = (artifact_root or self.project_root / ".game-agent-artifacts").resolve()
        self.config = config if isinstance(config, AciConfig) else AciConfig(**(config or {}))
        self.runner = runner
        self.validator_factory = validator_factory
        self.checkpoint_count = 0
        self.typed_mutation_count = 0
        self.escape_hatch_count = 0

    def execute(self, action: dict[str, Any]) -> dict[str, Any]:
        tool = str(action.get("tool", ""))
        args = action.get("arguments", {})
        if not isinstance(args, dict):
            return self._error(tool, "invalid_arguments", "Arguments must be an object.")
        if tool in CONTROL_TOOL_NAMES:
            return self._execute_control(tool, args)
        if tool not in MUTATION_TOOL_NAMES:
            return self._error(tool, "unknown_mutation", f"Unknown mutation tool: {tool}")
        if not self.config.enabled or not self.config.typed_mutations_enabled:
            return self._unavailable(tool, "Typed Unity mutations are disabled by configuration.")
        try:
            paths = self._target_paths(tool, args)
            checkpoint = self.create_checkpoint(paths, operation=tool)
            if tool == "unity_execute_csharp":
                self.escape_hatch_count += 1
            else:
                self.typed_mutation_count += 1
            if tool == "unity_script_patch":
                result = self._script_patch(args)
            elif tool == "unity_execute_csharp":
                result = self._execute_csharp(args)
            else:
                result = self._execute_editor_request(tool, args)
            extra = dict(result.get("extra", {}))
            extra.update(
                aci=True,
                aci_mutation=True,
                mutation_tool=tool,
                checkpoint_id=checkpoint["checkpoint_id"],
                checkpoint_manifest=checkpoint["manifest_ref"],
                changed_paths=paths,
            )
            if int(result.get("returncode", -1)) == 0:
                extra.update(
                    evidence_sources=[f"checkpoint:{checkpoint['checkpoint_id']}", *paths],
                    evidence_status="observed",
                    evidence_claim=f"Executed checkpointed Unity mutation {tool} for {', '.join(paths)}.",
                )
            result["extra"] = extra
            return result
        except (OSError, ValueError, RuntimeError) as exc:
            return self._error(tool, "mutation_failed", str(exc))

    def create_checkpoint(self, paths: list[str], *, operation: str) -> dict[str, Any]:
        checkpoint_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        root = self.artifact_root / "checkpoints" / checkpoint_id
        files_root = root / "files"
        files_root.mkdir(parents=True, exist_ok=False)
        records: list[dict[str, Any]] = []
        for relative in paths:
            target = self._project_path(relative, allow_missing=True)
            record = {
                "path": relative,
                "exists": target.is_file(),
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else "",
            }
            if target.is_file():
                destination = files_root / Path(relative.replace("\\", "/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, destination)
            meta = Path(f"{target}.meta")
            if meta.is_file():
                meta_relative = f"{relative}.meta"
                destination = files_root / Path(meta_relative.replace("\\", "/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(meta, destination)
                record["meta_path"] = meta_relative
                record["meta_sha256"] = hashlib.sha256(meta.read_bytes()).hexdigest()
            records.append(record)
        manifest = {
            "schema_version": "game-agent-unity-checkpoint-v1",
            "checkpoint_id": checkpoint_id,
            "operation": operation,
            "project_root": str(self.project_root),
            "created_at": time.time(),
            "files": records,
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.checkpoint_count += 1
        return {
            **manifest,
            "manifest_ref": manifest_path.relative_to(self.artifact_root).as_posix(),
        }

    def metrics(self) -> dict[str, Any]:
        total = self.typed_mutation_count + self.escape_hatch_count
        return {
            "typed_mutation_calls": self.typed_mutation_count,
            "escape_hatch_calls": self.escape_hatch_count,
            "escape_hatch_ratio": self.escape_hatch_count / total if total else 0.0,
            "checkpoints_created": self.checkpoint_count,
        }

    def _target_paths(self, tool: str, args: dict[str, Any]) -> list[str]:
        if tool == "unity_script_patch":
            values = [self._required(args, "path")]
        elif tool == "unity_execute_csharp":
            raw = args.get("target_paths", [])
            if not isinstance(raw, list) or not raw:
                raise ValueError("target_paths must be a non-empty array")
            values = [str(value) for value in raw]
        elif tool == "unity_prefab_create":
            values = [self._required(args, "source_asset_path"), self._required(args, "prefab_path")]
        else:
            values = [self._required(args, "asset_path")]
        normalized = list(dict.fromkeys(self._normalize_relative(value) for value in values))
        for value in normalized:
            self._project_path(value, allow_missing=tool in {"unity_prefab_create", "unity_asset_import"})
        return normalized

    def _script_patch(self, args: dict[str, Any]) -> dict[str, Any]:
        relative = self._normalize_relative(self._required(args, "path"))
        target = self._project_path(relative)
        raw = target.read_bytes()
        expected = self._required(args, "expected_sha256").casefold()
        actual = hashlib.sha256(raw).hexdigest()
        if actual != expected:
            raise ValueError(f"Source hash changed: expected {expected}, found {actual}")
        old = str(args.get("old_text", ""))
        new = str(args.get("new_text", ""))
        text = raw.decode("utf-8")
        occurrences = text.count(old)
        if not old or occurrences != 1:
            raise ValueError(f"old_text must match exactly once; found {occurrences}")
        target.write_text(text.replace(old, new, 1), encoding="utf-8")
        payload = {
            "status": "ok",
            "path": relative,
            "before_sha256": actual,
            "after_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "replacement_count": 1,
            "refresh_required": True,
            "recompile_required": True,
        }
        return self._ok("unity_script_patch", payload)

    def _execute_editor_request(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        editor = find_unity_editor(self.project_root, self.config.editor_path)
        if editor is None:
            return self._unavailable(tool, "Unity Editor not found; checkpoint was retained.")
        run_dir = self.artifact_root / "aci-runs" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=False)
        request_path = run_dir / "request.json"
        output_path = run_dir / "result.json"
        log_path = run_dir / "unity.log"
        request_path.write_text(
            json.dumps({"operation": tool, "arguments": args}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        bridge = self._install_bridge("GameAgentAciBridge.cs")
        command = [
            str(editor), "-batchmode", "-quit", "-projectPath", str(self.project_root),
            "-executeMethod", "GameAgentAciBridge.Execute",
            "-gameAgentAciRequest", str(request_path),
            "-gameAgentAciOutput", str(output_path),
            "-logFile", str(log_path),
        ]
        try:
            completed = self.runner(command, self.config.timeout_seconds)
        finally:
            self._remove_helper(*bridge)
        if completed.returncode != 0 or not output_path.is_file():
            tail = self._log_tail(log_path)
            raise RuntimeError(f"Unity mutation failed ({completed.returncode}); output={output_path.is_file()}\n{tail}")
        payload = json.loads(output_path.read_text(encoding="utf-8"))
        if payload.get("status") != "ok":
            raise RuntimeError(str(payload.get("message", "Unity mutation failed")))
        return self._ok(tool, payload, extra={"unity_log": str(log_path), "command": command})

    def _execute_csharp(self, args: dict[str, Any]) -> dict[str, Any]:
        editor = find_unity_editor(self.project_root, self.config.editor_path)
        if editor is None:
            return self._unavailable("unity_execute_csharp", "Unity Editor not found; checkpoint was retained.")
        run_dir = self.artifact_root / "aci-runs" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        run_dir.mkdir(parents=True, exist_ok=False)
        output_path = run_dir / "result.json"
        log_path = run_dir / "unity.log"
        code = self._required(args, "code")
        helper_source = (
            "using System.IO;\nusing UnityEditor;\nusing UnityEngine;\n"
            "public static class GameAgentAciEscape {\n"
            "  public static void Execute() {\n"
            f"    {code}\n"
            "    var args = System.Environment.GetCommandLineArgs();\n"
            "    var path = args[System.Array.IndexOf(args, \"-gameAgentAciOutput\") + 1];\n"
            "    File.WriteAllText(path, \"{\\\"status\\\":\\\"ok\\\",\\\"escape_hatch\\\":true}\");\n"
            "    AssetDatabase.SaveAssets(); AssetDatabase.Refresh();\n"
            "  }\n}\n"
        )
        helper = self._install_helper("GameAgentAciEscape.cs", helper_source)
        command = [
            str(editor), "-batchmode", "-quit", "-projectPath", str(self.project_root),
            "-executeMethod", "GameAgentAciEscape.Execute",
            "-gameAgentAciOutput", str(output_path), "-logFile", str(log_path),
        ]
        try:
            completed = self.runner(command, self.config.timeout_seconds)
        finally:
            self._remove_helper(*helper)
        if completed.returncode != 0 or not output_path.is_file():
            raise RuntimeError(
                f"unity_execute_csharp failed ({completed.returncode})\n{self._log_tail(log_path)}"
            )
        return self._ok(
            "unity_execute_csharp",
            json.loads(output_path.read_text(encoding="utf-8")),
            extra={"unity_log": str(log_path), "command": command, "escape_hatch": True},
        )

    def _execute_control(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool == "unity_hot_reload":
            return self._unavailable(
                tool,
                "No live Unity Editor bridge is connected; use unity_recompile to converge disk changes.",
            )
        modes = ["compile"] if tool == "unity_recompile" else list(args.get("modes", []))
        if tool == "unity_validate" and (
            not modes or any(mode not in {"editmode", "playmode"} for mode in modes)
        ):
            return self._error(tool, "invalid_modes", "modes must contain editmode and/or playmode")
        directory = self.artifact_root / "validation" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
        summary = self.validator_factory(
            self.project_root,
            directory,
            {
                "editor_path": self.config.editor_path,
                "modes": modes,
                "timeout_seconds": self.config.timeout_seconds,
            },
        ).run()
        success = summary.get("status") == "passed"
        claim = f"Unity {', '.join(modes)} validation {'passed' if success else 'did not pass'}."
        return {
            "output": json.dumps(summary, ensure_ascii=False, indent=2),
            "returncode": 0 if success else -2,
            "exception_info": "" if success else claim,
            "extra": {
                "aci": True,
                "aci_control": True,
                "control_tool": tool,
                "validation_modes": modes,
                "structured": summary,
                "evidence_sources": [f"validation:{directory.relative_to(self.artifact_root).as_posix()}"],
                "evidence_status": "runtime_verified" if success else "observed",
                "evidence_claim": claim,
            },
        }

    def _install_bridge(self, name: str) -> tuple[Path, list[Path]]:
        source = importlib.resources.files("game_agent.aci") / "editor" / name
        return self._install_helper(name, source.read_text(encoding="utf-8"))

    def _install_helper(self, name: str, source: str) -> tuple[Path, list[Path]]:
        target = self.project_root / "Assets" / "Editor" / name
        if target.exists():
            raise RuntimeError(f"Refusing to overwrite existing Unity helper: {target}")
        missing: list[Path] = []
        cursor = target.parent
        while cursor != self.project_root and not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return target, missing

    @staticmethod
    def _remove_helper(target: Path, created_directories: list[Path]) -> None:
        if target.is_file():
            target.unlink()
        meta = Path(f"{target}.meta")
        if meta.is_file():
            meta.unlink()
        for directory in created_directories:
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
            directory_meta = Path(f"{directory}.meta")
            if not directory.exists() and directory_meta.is_file():
                directory_meta.unlink()

    def _project_path(self, value: str, *, allow_missing: bool = False) -> Path:
        relative = self._normalize_relative(value)
        target = (self.project_root / relative).resolve()
        if target != self.project_root and self.project_root not in target.parents:
            raise ValueError(f"Path escapes Unity project: {value}")
        if not allow_missing and not target.is_file():
            raise ValueError(f"Target does not exist: {relative}")
        return target

    @staticmethod
    def _normalize_relative(value: str) -> str:
        normalized = value.replace("\\", "/").lstrip("./")
        if not normalized or not normalized.casefold().startswith("assets/"):
            raise ValueError(f"Unity mutation paths must be project-relative Assets/... paths: {value}")
        return normalized

    @staticmethod
    def _required(args: dict[str, Any], key: str) -> str:
        value = str(args.get(key, "")).strip()
        if not value:
            raise ValueError(f"{key} must be non-empty")
        return value

    @staticmethod
    def _log_tail(path: Path) -> str:
        if not path.is_file():
            return ""
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:])

    @staticmethod
    def _ok(tool: str, payload: dict[str, Any], *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": 0,
            "exception_info": "",
            "extra": {"aci": True, "mutation_tool": tool, "structured": payload, **(extra or {})},
        }

    @classmethod
    def _unavailable(cls, tool: str, reason: str) -> dict[str, Any]:
        payload = {"status": "unavailable", "reason": reason}
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": -2,
            "exception_info": reason,
            "extra": {"aci": True, "mutation_tool": tool, "structured": payload},
        }

    @staticmethod
    def _error(tool: str, code: str, message: str) -> dict[str, Any]:
        payload = {"status": "error", "error_code": code, "message": message}
        return {
            "output": json.dumps(payload, ensure_ascii=False, indent=2),
            "returncode": -2,
            "exception_info": message,
            "extra": {"aci": True, "mutation_tool": tool, "structured": payload},
        }
