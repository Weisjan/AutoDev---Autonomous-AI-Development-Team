from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from autodev.model_execution import ModelExecution
from autodev.model_policy import ResolvedModelPolicy


class GeneratedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Workspace-relative POSIX path for the generated file.")
    content: str

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        parts = [part for part in normalized.split("/") if part]
        if (
            not normalized
            or normalized.startswith("/")
            or ".." in parts
            or any(":" in part for part in parts)
        ):
            raise ValueError("generated file paths must stay inside the workspace")
        return "/".join(parts)


class CodeGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str
    files: list[GeneratedFile]
    assumptions: list[str] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: Literal["info", "warning", "error"]
    message: str
    file_path: str | None = None
    line: int | None = Field(default=None, ge=1)


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    risk_level: Literal["low", "medium", "high"]
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)


class TestRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str]
    exit_code: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    skipped: bool = False
    reason: str | None = None
    failure_kind: Literal["code", "infrastructure", "baseline"] | None = None

    @property
    def baseline_failed(self) -> bool:
        return self.failure_kind == "baseline"

    @property
    def infrastructure_failed(self) -> bool:
        return self.failure_kind == "infrastructure"

    @property
    def passed(self) -> bool:
        return (
            self.exit_code == 0
            and not self.timed_out
            and not self.skipped
            and self.failure_kind is None
        )

    def combined_output(self) -> str:
        chunks = []
        if self.reason:
            chunks.append(f"reason: {self.reason}")
        if self.stdout:
            chunks.append(f"stdout:\n{self.stdout}")
        if self.stderr:
            chunks.append(f"stderr:\n{self.stderr}")
        return "\n\n".join(chunks)


class AttemptLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iteration: int
    generated: CodeGenerationResult
    test_result: TestRunResult


class WorkflowResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str
    succeeded: bool
    attempts: list[AttemptLog]
    review: ReviewResult | None = None
    workspace: str
    stopped_reason: str
    model_calls_reserved: int
    report_version: int = Field(default=1, ge=1, le=2)
    model_policy: ResolvedModelPolicy | None = None
    model_executions: list[ModelExecution] = Field(default_factory=list)
