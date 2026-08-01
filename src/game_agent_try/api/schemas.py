from typing import Literal

from pydantic import BaseModel, Field


RunStatus = Literal["pending", "running", "submitted", "failed", "cancelled", "timed_out"]


class RunCreate(BaseModel):
    task: str = Field(min_length=1, max_length=20000)
    config_path: str = "configs/kitchen_chaos.json"
    project_path: str | None = None


class ArtifactInfo(BaseModel):
    name: str
    size: int
    created_at: str
    download_url: str
