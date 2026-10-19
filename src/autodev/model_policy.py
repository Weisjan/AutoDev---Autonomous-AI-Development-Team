"""Trusted, versioned model choices. Catalog membership never proves account access."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["architect", "developer", "reviewer"]
Effort = Literal["low", "medium", "high", "xhigh"]
ModelName = Literal["gpt-6-astra", "gpt-6.1-sol"]
Preset = Literal["fast", "balanced", "maximum_quality"]
ROLES: tuple[Role, ...] = ("architect", "developer", "reviewer")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RoleOverride(FrozenModel):
    model: ModelName | None = None
    reasoning_effort: Effort | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if self.model is None and self.reasoning_effort is None:
            raise ValueError("Provide a model or reasoning effort override")
        return self


class RoleOverrides(FrozenModel):
    architect: RoleOverride | None = None
    developer: RoleOverride | None = None
    reviewer: RoleOverride | None = None


class ModelPolicy(FrozenModel):
    kind: Literal["selection"] = "selection"
    preset: Preset = "balanced"
    overrides: RoleOverrides = Field(default_factory=RoleOverrides)


class ResolvedRole(FrozenModel):
    # Legacy model names remain supported without expanding the explicit-policy registry.
    model: str | None = Field(default=None, max_length=200)
    reasoning_effort: Effort | None = None
    model_source: Literal["legacy", "preset", "operator", "override"] = "legacy"
    effort_source: Literal["legacy", "preset", "operator", "override"] = "legacy"


class ResolvedModelPolicy(FrozenModel):
    kind: Literal["resolved"] = "resolved"
    version: Literal[1] = 1
    preset: Preset | None = None
    preset_revision: Literal[1] = 1
    architect: ResolvedRole
    developer: ResolvedRole
    reviewer: ResolvedRole

    @model_validator(mode="after")
    def explicit_policy_is_complete(self):
        if self.preset is not None and any(
            getattr(self, role).model not in {"gpt-6-astra", "gpt-6.1-sol"}
            or getattr(self, role).reasoning_effort is None
            for role in ROLES
        ):
            raise ValueError("Resolved preset requires supported explicit settings for every role")
        return self

    def for_role(self, role: Role) -> ResolvedRole:
        return getattr(self, role)


# Phase 1's deliberately bounded subset, not an assertion of account entitlement.
PRESETS: dict[Preset, tuple[tuple[ModelName, Effort], ...]] = {
    "fast": (("gpt-6.1-sol", "medium"), ("gpt-6.1-sol", "low"), ("gpt-6.1-sol", "medium")),
    "balanced": (("gpt-6-astra", "high"), ("gpt-6.1-sol", "high"), ("gpt-6-astra", "high")),
    "maximum_quality": (
        ("gpt-6-astra", "xhigh"),
        ("gpt-6.1-sol", "xhigh"),
        ("gpt-6-astra", "xhigh"),
    ),
}


def resolve_policy(
    policy: ModelPolicy | ResolvedModelPolicy | None,
    developer_model: str | None = None,
    reviewer_model: str | None = None,
    operator: RoleOverrides | None = None,
) -> ResolvedModelPolicy:
    if isinstance(policy, ResolvedModelPolicy):
        return policy  # Resume uses the saved snapshot, never today's preset table.
    if policy is None:
        return ResolvedModelPolicy(
            architect=ResolvedRole(model=developer_model),
            developer=ResolvedRole(model=developer_model),
            reviewer=ResolvedRole(model=reviewer_model),
        )
    roles = {}
    for role, (model, effort) in zip(ROLES, PRESETS[policy.preset], strict=True):
        values = dict(
            model=model, reasoning_effort=effort, model_source="preset", effort_source="preset"
        )
        for source, overrides in (("operator", operator), ("override", policy.overrides)):
            override = getattr(overrides, role) if overrides else None
            if override:
                if override.model is not None:
                    values.update(model=override.model, model_source=source)
                if override.reasoning_effort is not None:
                    values.update(reasoning_effort=override.reasoning_effort, effort_source=source)
        roles[role] = ResolvedRole(**values)
    return ResolvedModelPolicy(preset=policy.preset, **roles)


def resolve_config(config) -> ResolvedModelPolicy:
    return resolve_policy(
        config.model_policy,
        config.agents.developer_model,
        config.agents.reviewer_model,
        config.model_overrides,
    )


def policy_options(operator: RoleOverrides | None = None) -> dict:
    return {
        "default_dashboard_preset": "balanced",
        "presets": {
            name: resolve_policy(ModelPolicy(preset=name), operator=operator).model_dump(
                mode="json"
            )
            for name in PRESETS
        },
        "models": ["gpt-6-astra", "gpt-6.1-sol"],
        "reasoning_efforts": ["low", "medium", "high", "xhigh"],
        "availability": "Account access unverified; catalog membership is not entitlement",
        "runtime_observations": "Unavailable from the current exec transport",
    }
