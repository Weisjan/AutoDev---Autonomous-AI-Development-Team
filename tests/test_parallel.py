import asyncio
import json
from decimal import Decimal
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock

import pytest

from autodev.agents import ReviewerAgent
from autodev.budget import ApiBudgetTracker
from autodev.config import AgentConfig, AutoDevConfig, ParallelConfig
from autodev.integration import IntegrationConflict, IntegrationManager, TaskWorktree
from autodev.parallel import ParallelOrchestrator, SandboxChecks, build_parallel_orchestrator
from autodev.parallel_schemas import IntegratedChecks, ParallelWorkflowReport
from autodev.planning import DevelopmentTask, TaskPlan, TaskPlanner
from autodev.providers import ProviderError, ProviderRateLimitError
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as RunResult
from autodev.workspace import Workspace


def make_plan(count=2):
    return TaskPlan(
        summary="independent tasks",
        tasks=[
            DevelopmentTask(
                id=f"task{i}",
                description=f"Implement module {i}",
                owned_files=[f"module{i}.py"],
                acceptance_criteria=[f"module{i} has value {i}"],
            )
            for i in range(count)
        ],
    )


class FakeIntegration(IntegrationManager):
    def __init__(self, repo):
        super().__init__(repo)
        self.commits = {}
        self.integrated = []
        self.conflict = False

    async def prepare(self):
        self.root.mkdir(parents=True)
        self.created = True
        self.integration.path.mkdir()
        self.base_commit = "0" * 40
        self.source_branch = "feature/source"

    async def create_task(self, task):
        tree = TaskWorktree(self.root / "tasks" / task.id, f"autodev/test/{task.id}")
        tree.path.mkdir(parents=True)
        self.tasks[task.id] = tree
        return tree

    async def commit_task(self, task, attempt):
        commit = f"{len(self.commits) + 1:040x}"
        self.commits[commit] = Workspace(self.tasks[task.id].path).snapshot_files()
        return commit

    async def integrate(self, commit):
        if self.conflict:
            raise IntegrationConflict(["module0.py"])
        Workspace(self.integration.path).write_generated_files(self.commits[commit])
        self.integrated.append(commit)
        return commit


def checks(pytest_code=0, ruff_code=0, output="", skipped=False):
    return IntegratedChecks(
        pytest=RunResult(command=["pytest"], exit_code=pytest_code, stdout=output, skipped=skipped),
        ruff=RunResult(command=["ruff"], exit_code=ruff_code, stdout=output, skipped=skipped),
    )


class FakeChecks:
    def __init__(self, sequence):
        self.sequence = sequence
        self.calls = 0

    async def run(self, workspace):
        assert workspace.is_dir()
        result = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        return result


class Developers:
    def __init__(self, overlap=False, error=None, incomplete=False, hang=False):
        self.active = 0
        self.peak = 0
        self.events = []
        self.feedback = []
        self.overlap = overlap
        self.barrier = asyncio.Event()
        self.error = error
        self.incomplete = incomplete
        self.hang = hang
        self.cancelled = 0

    def __call__(self, worktree):
        owner = worktree.name
        controller = self

        class Client:
            async def generate_code(self, prompt, context, failure):
                assert f"module{owner[-1]}.py" in prompt
                controller.active += 1
                controller.peak = max(controller.peak, controller.active)
                controller.events.append(("start", owner, monotonic()))
                controller.feedback.append((owner, failure))
                if controller.active == 2:
                    controller.barrier.set()
                try:
                    if controller.overlap:
                        await asyncio.wait_for(controller.barrier.wait(), 1)
                        await asyncio.sleep(0.02)  # Exceed coarse Windows monotonic clock ticks.
                    await asyncio.sleep(0)
                    if controller.hang:
                        await asyncio.Future()
                    if controller.error and owner == "task0":
                        raise controller.error
                    files = (
                        []
                        if controller.incomplete and owner == "task0"
                        else [GeneratedFile(path=f"module{owner[-1]}.py", content="value = 1\n")]
                    )
                    return CodeGenerationResult(summary="implemented", files=files)
                except asyncio.CancelledError:
                    controller.cancelled += 1
                    raise
                finally:
                    controller.events.append(("finish", owner, monotonic()))
                    controller.active -= 1

        return Client()


def setup(tmp_path, developers=None, sequence=None, **limits):
    config = AutoDevConfig(
        agents=AgentConfig(api_budget_usd=Decimal("10")), parallel=ParallelConfig(**limits)
    )
    integration = FakeIntegration(tmp_path)
    developers = developers or Developers()
    runner = FakeChecks(sequence or [checks()])
    budget = ApiBudgetTracker(Decimal("10"), Decimal("0.05"))
    reviewer = AsyncMock()
    reviewer.review.return_value = ReviewResult(approved=True, risk_level="low", summary="OK")
    planner = AsyncMock()
    planner.plan.return_value = make_plan()
    workflow = ParallelOrchestrator(
        config,
        TaskPlanner(planner),
        developers,
        ReviewerAgent(reviewer, budget),
        integration,
        runner,
        budget,
    )
    return workflow, developers, integration, runner, reviewer


def test_real_overlapping_agent_execution_and_isolated_workspaces(tmp_path):
    workflow, developers, integration, runner, reviewer = setup(tmp_path, Developers(overlap=True))
    report = asyncio.run(workflow.run_task("two modules", plan=make_plan(4)))
    assert report.succeeded
    assert developers.peak == 2
    # Both model calls entered before either exited; serial execution cannot pass the barrier.
    assert [event[0] for event in developers.events[:2]] == ["start", "start"]
    starts = [event[2] for event in developers.events[:2]]
    finishes = [event[2] for event in developers.events if event[0] == "finish"]
    assert max(starts) < min(finishes)
    assert len({result.worktree for result in report.tasks}) == 4
    assert len({result.branch for result in report.tasks}) == 4
    for tree in integration.tasks.values():
        assert len(list(tree.path.glob("*.py"))) == 1
    assert len(list(integration.integration.path.glob("*.py"))) == 4
    assert report.source_branch == "feature/source"
    assert runner.calls == 1
    reviewer.review.assert_awaited_once()
    persisted = ParallelWorkflowReport.model_validate_json(Path(report.report_path).read_text())
    assert persisted == report
    assert all(result.attempts[0].duration_seconds > 0 for result in report.tasks)


def test_configured_single_worker_has_no_overlap(tmp_path):
    workflow, developers, _, _, _ = setup(tmp_path, concurrency=1)
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.succeeded
    assert developers.peak == 1
    assert [event[0] for event in developers.events] == ["start", "finish", "start", "finish"]


def test_only_responsible_owner_receives_correction_and_error_output(tmp_path):
    workflow, developers, _, runner, _ = setup(
        tmp_path,
        sequence=[checks(pytest_code=1, output="module0.py:3: assertion failed"), checks()],
    )
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.succeeded
    assert [len(result.attempts) for result in report.tasks] == [2, 1]
    assert report.rounds[0].correction_tasks == ["task0"]
    assert "assertion failed" in developers.feedback[-1][1]
    assert runner.calls == 2


def test_ruff_failure_also_triggers_correction(tmp_path):
    workflow, _, _, _, _ = setup(
        tmp_path, sequence=[checks(ruff_code=1, output="module1.py:1: F821"), checks()]
    )
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.succeeded
    assert [len(result.attempts) for result in report.tasks] == [1, 2]


def test_ambiguous_failures_are_bounded_to_three_corrections(tmp_path):
    workflow, _, _, runner, reviewer = setup(tmp_path, sequence=[checks(pytest_code=1)])
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert not report.succeeded
    assert report.integration_status == "checks_failed"
    assert [len(result.attempts) for result in report.tasks] == [4, 4]
    assert runner.calls == 4
    reviewer.review.assert_not_awaited()


@pytest.mark.parametrize(
    "developers",
    [
        Developers(error=ProviderRateLimitError("usage limit reached")),
        Developers(error=ProviderError("authentication failed")),
        Developers(incomplete=True),
    ],
)
def test_agent_failure_does_not_integrate_partial_batch(tmp_path, developers):
    workflow, _, integration, runner, reviewer = setup(tmp_path, developers)
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.integration_status == "agent_failed"
    assert not report.succeeded
    assert integration.integrated == []
    assert report.tasks[0].status == "failed"
    assert report.tasks[0].attempts[0].error
    assert not list(integration.tasks["task0"].path.glob("*.py"))
    assert runner.calls == 0
    reviewer.review.assert_not_awaited()


def test_conflicts_are_reported_and_worktrees_retained(tmp_path):
    workflow, _, integration, runner, _ = setup(tmp_path)
    integration.conflict = True
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.integration_status == "conflict"
    assert report.conflicts == ["module0.py"]
    assert integration.integration.path.exists()
    assert runner.calls == 0


def test_skipped_validation_cannot_produce_success_or_review(tmp_path):
    workflow, _, _, _, reviewer = setup(tmp_path, sequence=[checks(skipped=True)])
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.integration_status == "validation_unavailable"
    assert not report.succeeded
    reviewer.review.assert_not_awaited()


def test_call_limit_prevents_further_model_calls(tmp_path):
    workflow, developers, integration, _, _ = setup(tmp_path, max_model_calls=1)
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.model_calls_reserved == 1
    assert len(developers.feedback) == 1
    assert report.integration_status == "agent_failed"
    assert not integration.integrated


def test_planner_is_called_when_no_saved_plan_is_provided(tmp_path):
    workflow, _, _, _, _ = setup(tmp_path)
    report = asyncio.run(workflow.run_task("two"))
    assert report.succeeded
    assert report.model_calls_reserved == 4  # planner, two developers, reviewer
    workflow.planner.client.plan.assert_awaited_once()


@pytest.mark.parametrize("deadline", ["agent", "workflow"])
def test_timeouts_cancel_agents_and_preserve_failure_report(tmp_path, monkeypatch, deadline):
    settings = {f"{deadline}_timeout_seconds": 1}
    workflow, developers, integration, _, _ = setup(tmp_path, Developers(hang=True), **settings)
    original = asyncio.wait_for

    async def fast_wait(awaitable, timeout):
        return await original(awaitable, 0.01 if timeout == 1 else timeout)

    monkeypatch.setattr("autodev.parallel.asyncio.wait_for", fast_wait)
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.integration_status == ("agent_failed" if deadline == "agent" else "timed_out")
    assert developers.cancelled == 2
    assert developers.active == 0
    assert not integration.integrated
    assert json.loads(Path(report.report_path).read_text())["succeeded"] is False


def test_review_rejection_does_not_mark_success(tmp_path):
    workflow, _, _, _, reviewer = setup(tmp_path)
    reviewer.review.return_value = ReviewResult(approved=False, risk_level="high", summary="reject")
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert not report.succeeded
    assert report.integration_status == "review_rejected"


def test_parallel_factory_rejects_paid_provider(tmp_path):
    with pytest.raises(ProviderError, match="requires codex_cli"):
        build_parallel_orchestrator(AutoDevConfig(provider="openai_api"), tmp_path)


def test_sandbox_checks_use_only_fixed_pytest_and_ruff_commands(tmp_path, monkeypatch):
    calls = []

    def environment_call(self, workspace, timeout, maximum):
        calls.append(("environment", None))
        return RunResult(command=["environment"], exit_code=0)

    def pytest_call(self, workspace, command, timeout, maximum):
        calls.append(("pytest", command))
        return RunResult(command=list(command), exit_code=0)

    def ruff_call(self, workspace, timeout, maximum):
        calls.append(("ruff", None))
        return RunResult(command=["ruff"], exit_code=0)

    monkeypatch.setattr("autodev.parallel.DockerSandbox.run_pytest", pytest_call)
    monkeypatch.setattr("autodev.parallel.DockerSandbox.run_ruff", ruff_call)
    monkeypatch.setattr("autodev.parallel.DockerSandbox.check_environment", environment_call)
    config = AutoDevConfig(sandbox={"backend": "docker"})
    assert asyncio.run(SandboxChecks(config).run(tmp_path)).passed
    assert calls == [
        ("environment", None),
        ("pytest", ["python", "-m", "pytest", "tests", "--tb=short", "-q"]),
        ("ruff", None),
    ]


@pytest.mark.parametrize("tool", ["pytest", "ruff", "environment"])
def test_infrastructure_failure_never_requests_corrections_or_review(tmp_path, tool):
    result = checks()
    failure = RunResult(
        command=[tool],
        exit_code=2,
        failure_kind="infrastructure",
        stderr="ModuleNotFoundError: No module named 'dotenv'",
    )
    setattr(result, tool, failure)
    workflow, developers, _, runner, reviewer = setup(tmp_path, sequence=[result])
    report = asyncio.run(workflow.run_task("two", plan=make_plan()))
    assert report.integration_status == "infrastructure_failed"
    assert not report.succeeded
    assert [len(task.attempts) for task in report.tasks] == [1, 1]
    assert len(developers.feedback) == 2
    assert runner.calls == 1
    assert report.rounds[0].correction_tasks == []
    assert report.model_calls_reserved == 2
    reviewer.review.assert_not_awaited()


def test_failed_preflight_skips_pytest_and_ruff(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "autodev.parallel.DockerSandbox.check_environment",
        lambda *args: RunResult(
            command=["environment"],
            exit_code=78,
            failure_kind="infrastructure",
            reason="Missing pydantic",
        ),
    )
    monkeypatch.setattr(
        "autodev.parallel.DockerSandbox.run_pytest", lambda *args: pytest.fail("pytest ran")
    )
    monkeypatch.setattr(
        "autodev.parallel.DockerSandbox.run_ruff", lambda *args: pytest.fail("Ruff ran")
    )
    result = asyncio.run(SandboxChecks(AutoDevConfig(sandbox={"backend": "docker"})).run(tmp_path))
    assert result.infrastructure_failed
    assert result.environment.exit_code == 78
    assert result.pytest.skipped and result.ruff.skipped
    assert not result.passed
