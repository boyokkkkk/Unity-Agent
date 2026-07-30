import hashlib
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from game_agent.framework.utils.serialize import recursive_merge
from game_agent.processes import terminate_process_tree


class LocalEnvironmentConfig(BaseModel):
    cwd: str = ""
    env: dict[str, str] = {}
    timeout: int = 30
    shell_executable: str = ""
    artifact_dir: str = ""
    observation_max_chars: int = Field(default=12000, ge=256)
    observation_max_lines: int = Field(default=200, ge=8)
    observation_head_lines: int = Field(default=120, ge=1)
    observation_tail_lines: int = Field(default=40, ge=1)


class LocalEnvironment:
    def __init__(self, *, config_class: type = LocalEnvironmentConfig, **kwargs):
        """Execute Windows PowerShell commands directly on the local machine."""
        self.config = config_class(**kwargs)
        self._tool_output_index = 0

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        """Execute a command in the local environment and return the result as a dict."""
        command = action.get("command", "")
        cwd = cwd or self.config.cwd or os.getcwd()
        validation_error = self._validate_command(command, cwd)
        if validation_error:
            return self._finalize_output(
                {
                    "output": "",
                    "returncode": -2,
                    "exception_info": validation_error,
                    "extra": {"blocked": True, "guard": "command_scope"},
                }
            )
        try:
            result = _run(
                command,
                cwd,
                os.environ | self.config.env,
                timeout or self.config.timeout,
                self.config.shell_executable,
            )
            output = {"output": result.stdout, "returncode": result.returncode, "exception_info": ""}
        except Exception as e:
            raw_output = getattr(e, "output", None)
            raw_output = (
                raw_output.decode("utf-8", errors="replace") if isinstance(raw_output, bytes) else (raw_output or "")
            )
            output = {
                "output": raw_output,
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {e}",
                "extra": {"exception_type": type(e).__name__, "exception": str(e)},
            }
        return self._finalize_output(output)

    def _validate_command(self, command: str, cwd: str) -> str:
        """Return an error message to block a command, or an empty string to allow it."""
        return ""

    def _finalize_output(self, output: dict[str, Any]) -> dict[str, Any]:
        """Persist full stdout and replace it with a bounded model observation."""
        finalized = dict(output)
        raw_output = str(output.get("output", "") or "")
        encoded = raw_output.encode("utf-8")
        digest = hashlib.sha256(encoded).hexdigest()
        lines = raw_output.splitlines()
        artifact_path = self._write_tool_output(raw_output, digest)
        preview, truncated = self._bounded_preview(
            raw_output,
            artifact_path=artifact_path,
            output_lines=len(lines),
            output_chars=len(raw_output),
            output_bytes=len(encoded),
        )
        metadata = {
            **output.get("extra", {}),
            "artifact_path": artifact_path,
            "output_sha256": digest,
            "output_lines": len(lines),
            "output_chars": len(raw_output),
            "output_bytes": len(encoded),
            "output_truncated": truncated,
        }
        finalized["output"] = preview
        finalized["extra"] = metadata
        return finalized

    def finalize_output(self, output: dict[str, Any]) -> dict[str, Any]:
        """Apply the same artifact and preview policy to non-shell tool output."""
        return self._finalize_output(output)

    def _write_tool_output(self, raw_output: str, digest: str) -> str:
        if not self.config.artifact_dir:
            return ""
        root = Path(self.config.artifact_dir).resolve()
        output_dir = root / "tool-outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        while True:
            self._tool_output_index += 1
            name = f"tool-{self._tool_output_index:04d}-{digest[:12]}.txt"
            destination = output_dir / name
            if not destination.exists():
                break
        destination.write_text(raw_output, encoding="utf-8")
        return destination.relative_to(root).as_posix()

    def _bounded_preview(
        self,
        raw_output: str,
        *,
        artifact_path: str,
        output_lines: int,
        output_chars: int,
        output_bytes: int,
    ) -> tuple[str, bool]:
        max_chars = self.config.observation_max_chars
        max_lines = self.config.observation_max_lines
        if output_chars <= max_chars and output_lines <= max_lines:
            return raw_output, False

        source_lines = raw_output.splitlines(keepends=True)
        # Reserve four header lines and one possible character-omission marker line.
        content_line_budget = max_lines - 5
        head_lines = min(self.config.observation_head_lines, max(1, content_line_budget - 1))
        tail_lines = min(self.config.observation_tail_lines, content_line_budget - head_lines)
        if output_lines > max_lines:
            selected = "".join(source_lines[:head_lines] + source_lines[-tail_lines:])
            showing = f"Selected first {head_lines} and last {tail_lines} lines; preview is also character-bounded."
        else:
            selected = raw_output
            showing = "Showing bounded first and last character segments."

        location = artifact_path or "artifact unavailable"
        header = (
            f"Output truncated: {output_lines:,} lines / {output_chars:,} chars / {output_bytes:,} bytes.\n"
            f"{showing}\n"
            f"Full output: {location}\n\n"
        )
        budget = max(0, max_chars - len(header))
        if len(selected) > budget:
            marker = "\n... output omitted ...\n"
            content_budget = max(0, budget - len(marker))
            head_chars = (content_budget * 2) // 3
            tail_chars = content_budget - head_chars
            selected = selected[:head_chars] + marker + (selected[-tail_chars:] if tail_chars else "")
        return (header + selected)[:max_chars], True

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return recursive_merge(self.config.model_dump(), platform.uname()._asdict(), os.environ, kwargs)

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": self.config.model_dump(mode="json"),
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }


def _run(
    command: str,
    cwd: str,
    env: dict[str, str],
    timeout: int,
    shell_executable: str = "",
) -> subprocess.CompletedProcess[str]:
    """Like subprocess.run, but kills the whole process group on timeout so no children are orphaned."""
    executable = (
        shell_executable
        or shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh")
        or "powershell.exe"
    )
    encoding_prelude = (
        "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false); "
        "$OutputEncoding = [Console]::OutputEncoding; "
    )
    arguments = [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        encoding_prelude + command,
    ]
    process = subprocess.Popen(
        arguments,
        shell=False,
        text=True,
        cwd=cwd,
        env=env,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
    )
    try:
        stdout, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        terminate_process_tree(process.pid)
        stdout, _ = process.communicate()
        raise subprocess.TimeoutExpired(command, timeout, output=stdout)
    return subprocess.CompletedProcess(arguments, process.returncode, stdout=stdout)
