"""Call-scoped audit collection; requested settings are never runtime observations."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from autodev.model_policy import ResolvedRole, Role


class ModelExecution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str = Field(default_factory=lambda: uuid4().hex)
    role: Role
    requested: ResolvedRole
    observed_model: None = None
    observed_reasoning_effort: None = None
    observation_status: Literal["unavailable"] = "unavailable"
    observation_source: None = None
    status: Literal["running", "succeeded", "failed", "cancelled"] = "running"
    error_kind: str | None = None


_collector: ContextVar[Callable[[ModelExecution], None] | None] = ContextVar(
    "autodev_model_execution_collector", default=None
)


@contextmanager
def capture_execution(collector: Callable[[ModelExecution], None]) -> Iterator[None]:
    token = _collector.set(collector)
    try:
        yield
    finally:
        _collector.reset(token)


@contextmanager
def capture_attempt(attempt) -> Iterator[None]:
    with capture_execution(lambda execution: setattr(attempt, "execution", execution)):
        yield


def begin_execution(role: Role, settings: ResolvedRole) -> ModelExecution:
    record = ModelExecution(role=role, requested=settings)
    collector = _collector.get()
    if collector:
        collector(record)
    return record
