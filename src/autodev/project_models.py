"""Bounded project plans and reports. No plan field can select a host command."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from autodev.parallel_schemas import IntegrationRound, ParallelTaskResult, ParallelWorkflowReport
from autodev.planning import DevelopmentTask
from autodev.schemas import GeneratedFile

Text = Annotated[str, Field(min_length=1, max_length=2000)]
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,39}$")]
# Keep the transport schema aligned with the path checks below. No glob, directory,
# command-line or pytest node-selector strings may masquerade as test file paths.
_SEGMENT = r"[A-Za-z0-9_-](?:[A-Za-z0-9_.-]*[A-Za-z0-9_-])?"
ProjectFilePath = Annotated[
    str,
    Field(
        max_length=180,
        pattern=rf"^{_SEGMENT}(?:/{_SEGMENT})*$",
        description="Portable relative file path; no directories, globs or hidden paths.",
    ),
]
OwnedFilePath = Annotated[
    str,
    Field(
        max_length=180,
        pattern=rf"^(?:{_SEGMENT}/)*{_SEGMENT}\.(?:py|md|json|txt|html|css)$",
        description="Exact code/documentation/data file; tests and control files are forbidden.",
    ),
]
TestFilePath = Annotated[
    str,
    Field(
        max_length=180,
        pattern=rf"^tests/(?:{_SEGMENT}/)*{_SEGMENT}\.py$",
        description="Exact existing trusted .py file under tests/. No directories, globs, commands "
        "or ::test selectors. AutoDev runs the final full suite separately.",
    ),
]


def project_path(value: str, *, writable=True) -> str:
    normalized = GeneratedFile(path=value, content="").path
    parts = normalized.split("/")
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(10)),
        *(f"lpt{i}" for i in range(10)),
    }
    if (
        normalized != value
        or len(value) > 180
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", value)
        or any(
            p.startswith(".") or p.endswith((".", " ")) or p.split(".")[0].casefold() in reserved
            for p in parts
        )
        or any(p.casefold() in {"node_modules", "__pycache__", "auth.json"} for p in parts)
    ):
        raise ValueError("Unsafe or nonportable project path")
    if writable and (
        value.rsplit(".", 1)[-1] not in {"py", "md", "json", "txt", "html", "css"}
        or any(p.casefold() in {"tests", "test"} for p in parts)
        or parts[-1].casefold().startswith(("test_", "conftest", "requirements", "package"))
    ):
        raise ValueError(
            "Project ownership excludes tests, dependencies, scripts and control files"
        )
    return value


def test_path(value: str) -> str:
    project_path(value, writable=False)
    if not value.startswith("tests/") or not value.endswith(".py"):
        raise ValueError("Testing requires explicit existing Python files under tests/")
    return value


class ProjectTask(DevelopmentTask):
    owned_files: list[OwnedFilePath] = Field(min_length=1, max_length=10)
    depends_on: list[Identifier] = Field(
        default_factory=list,
        max_length=8,
        description="Prerequisite task IDs; no cycles, self or later-milestone references.",
    )
    test_paths: list[TestFilePath] = Field(min_length=1, max_length=20)

    @field_validator("owned_files")
    @classmethod
    def validate_files(cls, paths):
        if not paths or len(paths) > 10 or len(set(p.casefold() for p in paths)) != len(paths):
            raise ValueError("Task ownership must be unique and bounded")
        return [project_path(p) for p in paths]

    @field_validator("test_paths")
    @classmethod
    def validate_tests(cls, paths):
        return [test_path(p) for p in paths]


class Component(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Identifier
    responsibility: Text
    files: list[ProjectFilePath] = Field(
        min_length=1,
        max_length=20,
        description="Exact paths present in repository_structure; cover every task-owned file.",
    )


class Interface(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Identifier = Field(description="Existing component ID, not a task or milestone ID.")
    target: Identifier = Field(description="Existing component ID, not a task or milestone ID.")
    contract: Text


class Milestone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Identifier
    description: Text
    task_ids: list[Identifier] = Field(
        min_length=1,
        max_length=8,
        description="Every project task belongs to exactly one milestone, in dependency order.",
    )
    acceptance_criteria: list[Text] = Field(min_length=1, max_length=10)
    test_paths: list[TestFilePath] = Field(min_length=1, max_length=20)

    @field_validator("test_paths")
    @classmethod
    def validate_tests(cls, paths):
        return [test_path(p) for p in paths]


class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Text
    summary: Text
    execution_profile: Literal["python"] = "python"
    technology_stack: list[Text] = Field(min_length=1, max_length=8)
    repository_structure: list[ProjectFilePath] = Field(
        min_length=1,
        max_length=80,
        description="File paths only, including every component/task file. Omit directory entries "
        "such as tests/ and hidden/control files such as .gitignore.",
    )
    components: list[Component] = Field(min_length=1, max_length=12)
    interfaces: list[Interface] = Field(max_length=20)
    tasks: list[ProjectTask] = Field(min_length=1, max_length=8)
    milestones: list[Milestone] = Field(min_length=1, max_length=4)
    acceptance_criteria: list[Text] = Field(min_length=1, max_length=20)
    testing_requirements: list[Text] = Field(min_length=1, max_length=20)
    risks: list[Text] = Field(max_length=12)
    assumptions: list[Text] = Field(max_length=12)

    @model_validator(mode="after")
    def consistent(self):
        if len(self.model_dump_json()) > 100_000:
            raise ValueError("Project plan exceeds its size limit")
        structure = [project_path(p, writable=False) for p in self.repository_structure]
        if len(set(p.casefold() for p in structure)) != len(structure):
            raise ValueError("Repository structure contains aliases")
        if any(a.casefold().startswith(b.casefold() + "/") for a in structure for b in structure):
            raise ValueError("Repository structure has a file/directory collision")
        tasks = {t.id: t for t in self.tasks}
        components = {c.id: c for c in self.components}
        if len(tasks) != len(self.tasks) or len(components) != len(self.components):
            raise ValueError("Duplicate task/component IDs")
        if len({m.id for m in self.milestones}) != len(self.milestones):
            raise ValueError("Duplicate milestone IDs")
        ownership = [p for t in self.tasks for p in t.owned_files]
        if any(p not in structure for p in ownership):
            raise ValueError("Task files are absent from the repository structure")
        component_files = [p for c in self.components for p in c.files]
        if any(p not in structure for p in component_files) or not set(ownership) <= set(
            component_files
        ):
            raise ValueError("Components must cover task-owned structure paths")
        if any(i.source not in components or i.target not in components for i in self.interfaces):
            raise ValueError("Unknown interface component")
        location = {}
        for index, milestone in enumerate(self.milestones):
            for task_id in milestone.task_ids:
                if task_id not in tasks or task_id in location:
                    raise ValueError("Milestones must partition all tasks exactly once")
                location[task_id] = index
        if set(location) != set(tasks):
            raise ValueError("Missing milestone task assignment")
        ancestors = {}

        def visit(task_id, visiting):
            if task_id in visiting:
                raise ValueError("Task dependency cycle")
            if task_id in ancestors:
                return ancestors[task_id]
            result = set()
            for dependency in tasks[task_id].depends_on:
                if dependency not in tasks or location[dependency] > location[task_id]:
                    raise ValueError("Missing or later-milestone dependency")
                result |= {dependency} | visit(dependency, visiting | {task_id})
            ancestors[task_id] = result
            return result

        for task in self.tasks:
            visit(task.id, set())
        for i, left in enumerate(self.tasks):
            for right in self.tasks[i + 1 :]:
                overlap = any(
                    a.casefold() == b.casefold()
                    or a.casefold().startswith(b.casefold() + "/")
                    or b.casefold().startswith(a.casefold() + "/")
                    for a in left.owned_files
                    for b in right.owned_files
                )
                if (
                    overlap
                    and left.id not in ancestors[right.id]
                    and right.id not in ancestors[left.id]
                ):
                    raise ValueError("Overlapping owners must have an explicit dependency order")
        return self


class DependencyEngine:
    def __init__(self, specification: ProjectSpec):
        self.specification = ProjectSpec.model_validate(specification)

    def ready(self, milestone: Milestone, validated: set[str], limit: int) -> list[ProjectTask]:
        result, owned = [], set()
        for task in self.specification.tasks:
            if (
                task.id in milestone.task_ids
                and task.id not in validated
                and set(task.depends_on) <= validated
            ):
                paths = {p.casefold() for p in task.owned_files}
                if owned & paths:
                    continue
                result.append(task)
                owned |= paths
                if len(result) == limit:
                    break
        return result


class ProjectTaskResult(ParallelTaskResult):
    task: ProjectTask
    base_commit: str = ""


class MilestoneState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    status: str = "pending"
    started_at: str = ""
    finished_at: str = ""
    commit: str | None = None


class ProjectRound(IntegrationRound):
    milestone_id: str
    correction_attempt: int = 0
    test_paths: list[str] = Field(default_factory=list)


class CheckpointEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1, le=100)
    at: str
    label: str
    commit: str


class ProjectReport(ParallelWorkflowReport):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    duration_seconds: float = Field(default=0, ge=0)
    mode: Literal["project"] = "project"
    specification: ProjectSpec | None = None
    tasks: list[ProjectTaskResult] = Field(default_factory=list)
    rounds: list[ProjectRound] = Field(default_factory=list)
    milestones: list[MilestoneState] = Field(default_factory=list)
    checkpoint_history: list[CheckpointEntry] = Field(default_factory=list)
    checkpoint_digest: str = ""
    checkpoint_safe: bool = False
    configuration_digest: str = ""
    validated_tasks: list[str] = Field(default_factory=list)
    active_milestone: str = ""
    workflow_limits: dict[str, int] = Field(default_factory=dict)
