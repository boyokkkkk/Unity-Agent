from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


BENCHMARK_SCHEMA_VERSION = "game-agent-benchmark-v1"
RESULT_SCHEMA_VERSION = "game-agent-benchmark-result-v1"


class BenchmarkTask(BaseModel):
    id: str
    task: str
    project_path: str
    config_path: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in value):
            raise ValueError("task id may contain only letters, digits, dot, underscore, and hyphen")
        return value


class ModelVariant(BaseModel):
    name: str
    model_name: str
    model_class: str = "litellm"
    model_kwargs: dict[str, Any] = Field(default_factory=dict)
    cost_tracking: Literal["default", "ignore_errors"] = "default"

    @field_validator("model_class")
    @classmethod
    def validate_component_name(cls, value: str) -> str:
        if not value or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_.-" for character in value):
            raise ValueError("model_class must be a controlled registry alias")
        return value


class SkillVariant(BaseModel):
    name: str
    enabled: bool = True
    paths: list[str] = Field(default_factory=list)


class AblationMatrix(BaseModel):
    models: list[ModelVariant]
    skills: list[SkillVariant] = Field(
        default_factory=lambda: [SkillVariant(name="no-skill", enabled=False)]
    )
    seeds: list[int] = Field(default_factory=lambda: [42])

    @field_validator("models", "skills", "seeds")
    @classmethod
    def require_non_empty(cls, value: list) -> list:
        if not value:
            raise ValueError("ablation axes must not be empty")
        return value


class ExecutionConfig(BaseModel):
    max_workers: int = Field(default=1, ge=1, le=64)
    retries: int = Field(default=1, ge=0, le=20)
    resume: bool = True
    retry_failed_on_resume: bool = True


class BenchmarkManifest(BaseModel):
    schema_version: Literal["game-agent-benchmark-v1"] = BENCHMARK_SCHEMA_VERSION
    benchmark_id: str
    adapter: str = "unity"
    output_dir: str = "artifacts/benchmarks"
    tasks: list[BenchmarkTask]
    matrix: AblationMatrix
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    @field_validator("tasks")
    @classmethod
    def validate_tasks(cls, value: list[BenchmarkTask]) -> list[BenchmarkTask]:
        if not value:
            raise ValueError("benchmark must contain at least one task")
        ids = [task.id for task in value]
        if len(ids) != len(set(ids)):
            raise ValueError("benchmark task ids must be unique")
        return value
