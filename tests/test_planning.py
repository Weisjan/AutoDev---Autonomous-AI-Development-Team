import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from autodev.config import ParallelConfig
from autodev.planning import DevelopmentTask, TaskPlan, TaskPlanner, responsible_tasks


def task(task_id="a", path="a.py"):
    return DevelopmentTask(
        id=task_id,
        description="Implement a module",
        owned_files=[path],
        acceptance_criteria=["returns the expected value"],
    )


@pytest.mark.parametrize(
    "path",
    [
        "../escape.py",
        "C:/escape.py",
        "/escape.py",
        "tests/test_x.py",
        "Tests/a.py",
        ".git/hook.py",
        ".codex/config.py",
        "conftest.py",
        "test_x.py",
        "a//b.py",
        "src/./b.py",
        "NUL.py",
        "a.py ",
        "x*.py",
        "a.json",
        "a\\b.py",
    ],
)
def test_plan_rejects_unsafe_and_control_file_ownership(path):
    with pytest.raises(ValidationError):
        task(path=path)


@pytest.mark.parametrize(
    "tasks",
    [
        [task(), task("b", "a.py")],
        [task(), task("a", "b.py")],
        [task(), task("b", "A.py")],
        [task(), task("b", "a.py/child.py")],
    ],
)
def test_plan_rejects_duplicate_and_overlapping_ownership(tasks):
    with pytest.raises(ValidationError):
        TaskPlan(summary="invalid", tasks=tasks)


def test_plan_requires_acceptance_criteria():
    with pytest.raises(ValidationError):
        DevelopmentTask.model_validate(task().model_dump() | {"acceptance_criteria": []})


def test_planner_validates_model_output_and_task_count():
    plan = TaskPlan(summary="two tasks", tasks=[task(), task("b", "b.py")])
    client = AsyncMock()
    client.plan.return_value = plan
    assert asyncio.run(TaskPlanner(client, 2).decompose("request", [])) == plan
    client.plan.assert_awaited_once_with("request", [], 2)
    with pytest.raises(ValueError, match="task limit"):
        asyncio.run(TaskPlanner(client, 1).decompose("request", []))


def test_failure_routing_matches_owned_files_and_handles_ambiguity():
    plan = TaskPlan(summary="two", tasks=[task(), task("b", "src/b.py")])
    assert responsible_tasks(plan, "src/b.py:12: F821") == {"b"}
    assert responsible_tasks(plan, "a.py:5: AssertionError") == {"a"}
    assert responsible_tasks(plan, "tests/test_fixed.py:4: assertion failed") == {"a", "b"}


@pytest.mark.parametrize(
    "setting,value",
    [
        ("concurrency", 0),
        ("concurrency", 3),
        ("max_tasks", 9),
        ("max_corrections", 4),
        ("max_model_calls", 0),
        ("workflow_timeout_seconds", 0),
        ("agent_timeout_seconds", 0),
    ],
)
def test_parallel_limits_are_bounded(setting, value):
    with pytest.raises(ValidationError):
        ParallelConfig(**{setting: value})
