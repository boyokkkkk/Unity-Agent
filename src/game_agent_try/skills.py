"""Small local Skill runtime used by both batch and console agents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from game_agent_try.logging import ExperimentLogger


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    triggers: tuple[str, ...]
    instructions: str
    path: Path


class SkillRuntime:
    """Discover Markdown Skills, match a task, and return verified instructions."""

    def __init__(
        self,
        paths: list[Path],
        *,
        logger: ExperimentLogger,
        max_prompt_chars: int = 8000,
    ) -> None:
        self.paths = [path.resolve() for path in paths]
        self.logger = logger
        self.max_prompt_chars = max(1, max_prompt_chars)
        self.skills: list[SkillDefinition] = []
        self.load_errors: list[tuple[Path, str]] = []
        self._discover()

    def _discover(self) -> None:
        discovered: dict[str, SkillDefinition] = {}
        for root in self.paths:
            candidates = [root] if root.is_file() else sorted(root.glob("**/SKILL.md")) if root.is_dir() else []
            for path in candidates:
                try:
                    skill = self._load(path)
                    discovered[skill.name] = skill
                except Exception as error:
                    self.load_errors.append((path, str(error)))
        self.skills = sorted(discovered.values(), key=lambda item: item.name)

    @staticmethod
    def _load(path: Path) -> SkillDefinition:
        text = path.read_text(encoding="utf-8-sig")
        if not text.startswith("---\n"):
            raise ValueError("SKILL.md must start with YAML front matter")
        try:
            header, instructions = text[4:].split("\n---\n", 1)
        except ValueError as error:
            raise ValueError("SKILL.md front matter is not terminated") from error
        metadata = yaml.safe_load(header) or {}
        name = str(metadata.get("name", "")).strip()
        description = str(metadata.get("description", "")).strip()
        raw_triggers = metadata.get("triggers", [])
        if not name or not description or not isinstance(raw_triggers, list):
            raise ValueError("Skill requires name, description, and a triggers list")
        triggers = tuple(str(item).strip().casefold() for item in raw_triggers if str(item).strip())
        instructions = instructions.strip()
        if not triggers or not instructions:
            raise ValueError("Skill requires at least one trigger and non-empty instructions")
        return SkillDefinition(name, description, triggers, instructions, path.resolve())

    def resolve(self, task: str) -> dict[str, str] | None:
        started = time.perf_counter()
        self.logger.emit(
            "skill_search_start",
            query=task[:500],
            skill_count=len(self.skills),
            search_paths=[str(path) for path in self.paths],
        )
        for path, error in self.load_errors:
            self.logger.emit("skill_apply_failed", skill_name=path.parent.name, skill_path=str(path), error=error)

        normalized = task.casefold()
        ranked = sorted(
            (
                (sum(1 for trigger in skill.triggers if trigger in normalized), skill)
                for skill in self.skills
            ),
            key=lambda item: (-item[0], item[1].name),
        )
        if not ranked or ranked[0][0] == 0:
            self.logger.emit("skill_not_found", reason="no_match", available_skills=len(self.skills))
            return None

        score, skill = ranked[0]
        self.logger.emit(
            "skill_matched",
            skill_name=skill.name,
            skill_path=str(skill.path),
            match_score=score,
            description=skill.description,
        )
        self.logger.emit("skill_apply_start", skill_name=skill.name, skill_path=str(skill.path))
        instructions = skill.instructions[: self.max_prompt_chars]
        truncated = len(instructions) < len(skill.instructions)
        self.logger.emit(
            "skill_apply_end",
            skill_name=skill.name,
            skill_path=str(skill.path),
            instruction_chars=len(instructions),
            truncated=truncated,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        return {"name": skill.name, "instructions": instructions}


def build_skill_runtime(
    config: dict[str, Any],
    logger: ExperimentLogger,
    *,
    config_path: Path,
) -> SkillRuntime | None:
    settings = config.get("skills", {})
    if settings.get("enabled", True) is False:
        return None
    paths = [Path(__file__).parent / "builtin_skills"]
    for raw_path in settings.get("paths", []):
        path = Path(raw_path)
        paths.append(path if path.is_absolute() else config_path.parent / path)
    return SkillRuntime(
        paths,
        logger=logger,
        max_prompt_chars=int(settings.get("max_prompt_chars", 8000)),
    )
