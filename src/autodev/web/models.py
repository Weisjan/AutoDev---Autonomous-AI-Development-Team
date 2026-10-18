from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository_id: str = Field(pattern=r"^[0-9a-f]{12}$")
    instructions: str = Field(min_length=8, max_length=20_000)
    concurrency: int = Field(default=2, ge=1, le=2)
    max_tasks: int = Field(default=4, ge=1, le=8)
    max_corrections: int = Field(default=3, ge=0, le=3)
    max_model_calls: int = Field(default=24, ge=3, le=48)
    workflow_timeout_seconds: int = Field(default=1800, ge=30, le=3600)
    example: bool = False
    mode: Literal["task", "project"] = "task"

    @model_validator(mode="after")
    def project_options(self):
        if self.mode == "project" and self.example:
            raise ValueError(
                "The v0.3 example is a task workflow; project mode uses existing tests"
            )
        return self

    @field_validator("instructions")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if len(value.strip()) < 8 or "\x00" in value:
            raise ValueError("Provide at least eight characters of task instructions")
        return value.strip()


class ResumeRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False
