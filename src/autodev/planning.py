from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autodev.schemas import GeneratedFile


def owned_path(value: str) -> str:
    """Exact, portable implementation paths; tests and control files are never owned."""
    normalized = GeneratedFile(path=value, content="").path
    parts = normalized.split("/")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if (
        normalized != value
        or not normalized.endswith(".py")
        or any(char in normalized for char in '<>"|?*')
        or any(ord(char) < 32 for char in normalized)
        or any(part.startswith(".") or part.rstrip(" .") != part for part in parts)
        or any(part.split(".")[0].casefold() in reserved for part in parts)
        or any(part.casefold() in {"tests", "test", "__pycache__"} for part in parts)
        or parts[-1].casefold() == "conftest.py"
        or parts[-1].casefold().startswith("test_")
    ):
        raise ValueError(
            "ownership must name a portable Python implementation file, not tests/control files"
        )
    return normalized


class DevelopmentTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")
    description: str = Field(min_length=1, max_length=8000)
    owned_files: list[str] = Field(min_length=1, max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=20)

    @field_validator("owned_files")
    @classmethod
    def validate_files(cls, paths: list[str]) -> list[str]:
        return [owned_path(path) for path in paths]

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_criteria(cls, criteria: list[str]) -> list[str]:
        if any(not item.strip() for item in criteria):
            raise ValueError("acceptance criteria cannot be blank")
        return criteria


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    tasks: list[DevelopmentTask] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def independent_ownership(self) -> TaskPlan:
        ids = [task.id for task in self.tasks]
        paths = [path.casefold() for task in self.tasks for path in task.owned_files]
        if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
            raise ValueError("tasks need unique IDs and disjoint file ownership")
        for path in paths:
            if any(other.startswith(path + "/") for other in paths):
                raise ValueError("file ownership cannot overlap parent paths")
        return self


class PlannerClient(Protocol):
    async def plan(self, request: str, files: list[GeneratedFile], max_tasks: int) -> TaskPlan: ...


class TaskPlanner:
    def __init__(self, client: PlannerClient, max_tasks: int = 4) -> None:
        self.client = client
        self.max_tasks = max_tasks

    async def decompose(self, request: str, files: list[GeneratedFile]) -> TaskPlan:
        plan = TaskPlan.model_validate(await self.client.plan(request, files, self.max_tasks))
        if len(plan.tasks) > self.max_tasks:
            raise ValueError("planner exceeded the configured task limit")
        return plan


def responsible_tasks(plan: TaskPlan, output: str) -> set[str]:
    """Match exact implementation paths; ambiguous/test-only failures go to all owners."""
    owners = {
        task.id
        for task in plan.tasks
        for path in task.owned_files
        if re.search(
            r"(?<![\w/])" + re.escape(path) + r"(?=[:\s\"')]|$)", output.replace("\\", "/")
        )
    }
    return owners or {task.id for task in plan.tasks}
