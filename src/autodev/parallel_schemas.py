from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autodev.planning import DevelopmentTask, TaskPlan
from autodev.schemas import ReviewResult, TestRunResult


class IntegratedChecks(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pytest: TestRunResult
    ruff: TestRunResult
    environment: TestRunResult | None = None

    @property
    def infrastructure_failed(self) -> bool:
        return any(
            result.infrastructure_failed
            for result in (self.pytest, self.ruff, self.environment)
            if result is not None
        )

    @property
    def passed(self) -> bool:
        return (
            self.pytest.passed
            and self.ruff.passed
            and (self.environment is None or self.environment.passed)
        )

    @property
    def unavailable(self) -> bool:
        return self.pytest.skipped or self.ruff.skipped

    def failure_output(self) -> str:
        return "\n\n".join(
            f"{name}:\n{result.combined_output()}"
            for name, result in (("pytest", self.pytest), ("ruff", self.ruff))
            if not result.passed
        )


class AgentAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    agent_id: str
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0
    commit: str | None = None
    error: str | None = None


class ParallelTaskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: DevelopmentTask
    branch: str
    worktree: str
    status: str = "pending"
    attempts: list[AgentAttempt] = Field(default_factory=list)


class IntegrationRound(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int
    commits: list[str] = Field(default_factory=list)
    checks: IntegratedChecks | None = None
    correction_tasks: list[str] = Field(default_factory=list)


class ParallelWorkflowReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request: str
    run_id: str
    started_at: str
    finished_at: str = ""
    duration_seconds: float = 0
    succeeded: bool = False
    integration_status: str = "pending"
    stopped_reason: str = ""
    source_branch: str = ""
    base_commit: str = ""
    integration_commit: str | None = None
    integration_branch: str
    integration_worktree: str
    plan: TaskPlan | None = None
    tasks: list[ParallelTaskResult] = Field(default_factory=list)
    rounds: list[IntegrationRound] = Field(default_factory=list)
    seed_commit: str | None = None
    review: ReviewResult | None = None
    planner_execution: AgentAttempt | None = None
    reviewer_execution: AgentAttempt | None = None
    conflicts: list[str] = Field(default_factory=list)
    model_calls_reserved: int = 0
    report_path: str | None = None
