from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .schema import ProjectGraph


class RoslynParseError(RuntimeError):
    pass


class RoslynCodeParser:
    """Run the repository's Roslyn syntax exporter and return a typed code graph."""

    def __init__(self, helper_project: Path | None = None):
        repository_root = Path(__file__).resolve().parents[3]
        self.helper_project = (
            helper_project
            or repository_root / "tools" / "roslyn-project-graph" / "RoslynProjectGraph.csproj"
        ).resolve()

    def parse(
        self,
        project_path: Path,
        *,
        output_path: Path,
        timeout_seconds: int = 300,
    ) -> ProjectGraph:
        project_path = project_path.resolve()
        if not (project_path / "Assets").is_dir():
            raise FileNotFoundError(f"Unity Assets directory not found: {project_path / 'Assets'}")
        if not self.helper_project.is_file():
            raise FileNotFoundError(f"Roslyn helper project not found: {self.helper_project}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = self._command()
        command.extend([
            "--project", str(project_path),
            "--output", str(output_path.resolve()),
        ])
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        if completed.returncode != 0 or not output_path.is_file():
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RoslynParseError(
                f"Roslyn exporter failed ({completed.returncode}): {detail[-4000:]}"
            )
        data: dict[str, Any] = json.loads(output_path.read_text(encoding="utf-8"))
        return ProjectGraph.from_dict(data)

    def validate_syntax(
        self,
        source: str,
        *,
        timeout_seconds: int = 30,
    ) -> list[dict[str, Any]]:
        """Parse a complete C# source file with Roslyn and return syntax errors."""
        completed = subprocess.run(
            [*self._command(), "--validate-stdin"],
            input=source,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        try:
            payload = json.loads(completed.stdout.strip())
        except json.JSONDecodeError as exc:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RoslynParseError(
                f"Roslyn syntax validation failed ({completed.returncode}): {detail[-4000:]}"
            ) from exc
        diagnostics = payload.get("diagnostics", [])
        if completed.returncode not in {0, 4} or not isinstance(diagnostics, list):
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise RoslynParseError(
                f"Roslyn syntax validation failed ({completed.returncode}): {detail[-4000:]}"
            )
        return [item for item in diagnostics if isinstance(item, dict)]

    def _command(self) -> list[str]:
        compiled_helper = (
            self.helper_project.parent
            / "bin"
            / "Release"
            / "net9.0"
            / "RoslynProjectGraph.dll"
        )
        sources = list(self.helper_project.parent.glob("*.cs"))
        helper_is_current = compiled_helper.is_file() and all(
            source.stat().st_mtime <= compiled_helper.stat().st_mtime
            for source in sources
        )
        if helper_is_current:
            return ["dotnet", str(compiled_helper)]
        return [
            "dotnet", "run", "--project", str(self.helper_project),
            "--configuration", "Release", "--",
        ]
