from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .logging import ExperimentLogger


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class WorkspaceTools:
    """Small, auditable tool surface used by the baseline agent."""

    def __init__(self, root: Path, logger: ExperimentLogger) -> None:
        self.root = root.resolve()
        self.logger = logger

    def _safe(self, relative: str | Path) -> Path:
        target = (self.root / relative).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Path escapes workspace: {relative}")
        return target

    def read_file(self, relative: str | Path) -> str:
        path = self._safe(relative)
        text = path.read_text(encoding="utf-8")
        self.logger.emit("tool", tool="read_file", path=str(path.relative_to(self.root)), bytes=len(text.encode()))
        return text

    def write_file(self, relative: str | Path, content: str) -> None:
        path = self._safe(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self.logger.emit("tool", tool="write_file", path=str(path.relative_to(self.root)), bytes=len(content.encode()))

    def run(self, command: list[str], *, timeout: int = 120) -> CommandResult:
        self.logger.emit("command_start", command=command)
        process = subprocess.run(
            command, cwd=self.root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        result = CommandResult(command, process.returncode, process.stdout or "", process.stderr or "")
        self.logger.emit("command_end", command=command, returncode=result.returncode,
                         stdout=result.stdout[-4000:], stderr=result.stderr[-4000:])
        return result
