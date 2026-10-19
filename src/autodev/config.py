from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, PositiveInt, field_validator, model_validator

from autodev.model_policy import ModelPolicy, ResolvedModelPolicy, RoleOverrides


class AgentConfig(BaseModel):
    developer_model: str | None = None
    reviewer_model: str | None = None
    max_iterations: PositiveInt = Field(default=3, le=3)
    api_budget_usd: Decimal = Field(default=Decimal("1.00"), ge=Decimal("0.00"))
    estimated_cost_per_model_call_usd: Decimal = Field(
        default=Decimal("0.05"),
        gt=Decimal("0.00"),
    )

    @field_validator("developer_model", "reviewer_model", mode="before")
    @classmethod
    def empty_string_is_none(cls, value: str | None) -> str | None:
        if value == "":
            return None
        return value


class SandboxConfig(BaseModel):
    backend: Literal["dry_run", "docker"] = "dry_run"
    docker_image: str = "autodev-sandbox:py311"
    timeout_seconds: PositiveInt = 30
    max_output_chars: PositiveInt = 20_000


class CodexCLIConfig(BaseModel):
    executable: str = Field(default="codex", min_length=1)
    timeout_seconds: PositiveInt = 180
    max_output_bytes: PositiveInt = 1_000_000


class ParallelConfig(BaseModel):
    concurrency: PositiveInt = Field(default=2, le=2)
    max_tasks: PositiveInt = Field(default=4, le=8)
    max_corrections: int = Field(default=3, ge=0, le=3)
    max_model_calls: PositiveInt = 24
    workflow_timeout_seconds: PositiveInt = 1800
    agent_timeout_seconds: PositiveInt = 240
    git_timeout_seconds: PositiveInt = 30


class AutoDevConfig(BaseModel):
    provider: Literal["codex_cli", "openai_api"] = "codex_cli"
    workspace_dir: Path = Path(".autodev/workspace")
    reset_workspace: bool = True
    agents: AgentConfig = Field(default_factory=AgentConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    codex_cli: CodexCLIConfig = Field(default_factory=CodexCLIConfig)
    parallel: ParallelConfig = Field(default_factory=ParallelConfig)
    model_policy: ModelPolicy | ResolvedModelPolicy | None = None
    model_overrides: RoleOverrides = Field(default_factory=RoleOverrides)

    @model_validator(mode="after")
    def codex_model_policy(self):
        if self.model_policy is not None and self.provider != "codex_cli":
            raise ValueError("Role model policies require codex_cli with ChatGPT authentication")
        if self.model_policy is None and any(
            getattr(self.model_overrides, role) is not None
            for role in ("architect", "developer", "reviewer")
        ):
            raise ValueError("Role overrides require an explicit model policy")
        return self


def _decimal_env(name: str, default: Decimal) -> Decimal:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return Decimal(value)


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def load_config_from_env() -> AutoDevConfig:
    load_dotenv()
    overrides = {}
    for role in ("architect", "developer", "reviewer"):
        values = {
            name: value
            for name, value in (
                ("model", os.getenv(f"AUTODEV_{role.upper()}_MODEL")),
                ("reasoning_effort", os.getenv(f"AUTODEV_{role.upper()}_REASONING_EFFORT")),
            )
            if value
        }
        if values:
            overrides[role] = values
    preset = os.getenv("AUTODEV_MODEL_PRESET") or None
    # Existing model-only variables keep their legacy semantics. New controls opt in.
    explicit = (
        preset
        or "architect" in overrides
        or any("reasoning_effort" in values for values in overrides.values())
    )
    agents = AgentConfig(
        developer_model=os.getenv("AUTODEV_DEVELOPER_MODEL") or None,
        reviewer_model=os.getenv("AUTODEV_REVIEWER_MODEL") or None,
        max_iterations=_int_env("AUTODEV_MAX_ITERATIONS", 3),
        api_budget_usd=_decimal_env("AUTODEV_API_BUDGET_USD", Decimal("1.00")),
        estimated_cost_per_model_call_usd=_decimal_env(
            "AUTODEV_ESTIMATED_COST_PER_MODEL_CALL_USD",
            Decimal("0.05"),
        ),
    )
    sandbox = SandboxConfig(
        backend=os.getenv("AUTODEV_SANDBOX_BACKEND", "dry_run"),
        docker_image=os.getenv("AUTODEV_DOCKER_IMAGE", "autodev-sandbox:py311"),
    )
    return AutoDevConfig(
        provider=os.getenv("AUTODEV_PROVIDER", "codex_cli"),
        workspace_dir=Path(os.getenv("AUTODEV_WORKSPACE", ".autodev/workspace")),
        agents=agents,
        model_policy=ModelPolicy(preset=preset or "balanced") if explicit else None,
        model_overrides=RoleOverrides.model_validate(overrides if explicit else {}),
        sandbox=sandbox,
        codex_cli=CodexCLIConfig(
            executable=os.getenv("AUTODEV_CODEX_EXECUTABLE", "codex"),
            timeout_seconds=_int_env("AUTODEV_CODEX_TIMEOUT_SECONDS", 180),
            max_output_bytes=_int_env("AUTODEV_CODEX_MAX_OUTPUT_BYTES", 1_000_000),
        ),
        parallel=ParallelConfig(
            concurrency=_int_env("AUTODEV_CONCURRENCY", 2),
            max_tasks=_int_env("AUTODEV_MAX_TASKS", 4),
            max_corrections=_int_env("AUTODEV_MAX_CORRECTIONS", 3),
            max_model_calls=_int_env("AUTODEV_MAX_MODEL_CALLS", 24),
            workflow_timeout_seconds=_int_env("AUTODEV_WORKFLOW_TIMEOUT_SECONDS", 1800),
            agent_timeout_seconds=_int_env("AUTODEV_AGENT_TIMEOUT_SECONDS", 240),
            git_timeout_seconds=_int_env("AUTODEV_GIT_TIMEOUT_SECONDS", 30),
        ),
    )
