import asyncio
from time import monotonic

import pytest
from project_fakes import ProjectChecks, project_repository, specification

from autodev.config import AutoDevConfig
from autodev.model_policy import ModelPolicy
from autodev.project import build_project_orchestrator
from autodev.project_models import ProjectSpec
from autodev.providers import CodexCLIProvider, ProviderModelUnavailableError
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult


@pytest.mark.parametrize("failure_role", [None, "architect", "developer", "reviewer"])
def test_real_provider_role_wiring_in_isolated_project_workflow(
    tmp_path, monkeypatch, failure_role
):
    repo = project_repository(tmp_path / "repository")
    barrier = asyncio.Event()
    calls, starts, ends = [], [], []
    core_entered = 0
    contents = {
        "base.py": "value = 1\n",
        "utility.py": "value = 2\n",
        "app.py": (
            "from base import value as base\nfrom utility import value as utility\n"
            "result = base + utility\n"
        ),
        "README.md": "# Offline role policy fixture\n",
    }

    async def execute(self, prompt, response_type, settings):
        nonlocal core_entered
        role = (
            "architect"
            if response_type is ProjectSpec
            else "reviewer"
            if response_type is ReviewResult
            else "developer"
        )
        calls.append((role, settings))
        if role == failure_role:
            raise ProviderModelUnavailableError("Requested model unavailable; no fallback")
        if role == "architect":
            return specification()
        if role == "reviewer":
            return ReviewResult(approved=True, risk_level="low", summary="Offline role fixture")
        task_id = self._workspace.name
        task = next(t for t in specification().tasks if t.id == task_id)
        if task_id in {"foundation", "utility"}:
            starts.append(monotonic())
            core_entered += 1
            if core_entered == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), 3)
            await asyncio.sleep(0.03)
            ends.append(monotonic())
        if task_id == "application":
            assert (self._workspace / "base.py").read_text() == contents["base.py"]
            assert (self._workspace / "utility.py").read_text() == contents["utility.py"]
        return CodeGenerationResult(
            summary="Offline",
            files=[GeneratedFile(path=p, content=contents[p]) for p in task.owned_files],
        )

    monkeypatch.setattr(CodexCLIProvider, "_execute", execute)
    config = AutoDevConfig(
        model_policy=ModelPolicy(
            preset="maximum_quality", overrides={"developer": {"reasoning_effort": "high"}}
        )
    )
    runner = build_project_orchestrator(config, repo)
    runner.checks = ProjectChecks()
    report = asyncio.run(runner.run_task("Build a composed repository"))
    assert report.model_policy.preset == "maximum_quality"
    if failure_role:
        assert not report.succeeded and report.error_kind == "model_unavailable"
        assert not any(r.correction_tasks for r in report.rounds)
        if failure_role == "architect":
            assert report.tasks == [] and len(calls) == 1
            assert report.planner_execution.error_kind == "model_unavailable"
        if failure_role == "developer":
            assert "reviewer" not in [role for role, _ in calls]
            assert all(len(t.attempts) <= 1 for t in report.tasks)
        if failure_role == "reviewer":
            assert report.reviewer_execution.error_kind == "model_unavailable"
        return
    assert report.succeeded, report.stopped_reason
    assert max(starts) < min(ends)
    assert report.model_calls_reserved == 6
    records = [report.planner_execution.execution, report.reviewer_execution.execution]
    records += [a.execution for t in report.tasks for a in t.attempts]
    assert len({r.call_id for r in records}) == 6
    assert all(r.observation_status == "unavailable" and r.observed_model is None for r in records)
    for role, settings in calls:
        assert settings.model == ("gpt-6.1-sol" if role == "developer" else "gpt-6-astra")
        assert settings.reasoning_effort == ("high" if role == "developer" else "xhigh")


def test_provider_failure_blocks_queued_calls_without_spending_budget(tmp_path):
    from test_parallel import Developers, make_plan, setup

    runner, models, integration, checks, reviewer = setup(
        tmp_path,
        Developers(error=ProviderModelUnavailableError("No model access")),
        concurrency=1,
    )
    report = asyncio.run(runner.run_task("Offline modules", plan=make_plan(4)))
    assert report.error_kind == "model_unavailable"
    assert report.model_calls_reserved == 1
    assert [t.status for t in report.tasks] == ["failed", "blocked", "blocked", "blocked"]
    assert [len(t.attempts) for t in report.tasks] == [1, 0, 0, 0]
    assert len(models.feedback) == 1
    assert checks.calls == 0 and not integration.integrated
    reviewer.review.assert_not_called()
