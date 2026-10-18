import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from project_fakes import (
    ProjectChecks,
    ProjectModels,
    git,
    project_repository,
    specification,
    workflow,
)
from pydantic import ValidationError

from autodev.architect import ProjectArchitect
from autodev.checkpoints import RecoveryRequired
from autodev.config import AutoDevConfig, ParallelConfig
from autodev.integration import IntegrationConflict
from autodev.parallel import SandboxChecks
from autodev.project_models import DependencyEngine, ProjectSpec
from autodev.schemas import TestRunResult as CheckResult


@pytest.fixture
def repo(tmp_path):
    return project_repository(tmp_path / "repository")


@pytest.mark.parametrize(
    "mutation",
    ["cycle", "missing", "ownership", "unsafe", "large", "milestone", "interface", "stack"],
)
def test_architecture_plan_validation(mutation):
    data = specification().model_dump()
    if mutation == "cycle":
        data["tasks"][0]["depends_on"] = ["utility"]
        data["tasks"][1]["depends_on"] = ["foundation"]
    elif mutation == "missing":
        data["tasks"][0]["depends_on"] = ["unknown"]
    elif mutation == "ownership":
        data["tasks"][1]["owned_files"] = ["base.py"]
    elif mutation == "unsafe":
        data["tasks"][0]["owned_files"] = ["../outside.py"]
    elif mutation == "large":
        data["tasks"] *= 3
    elif mutation == "milestone":
        data["milestones"][0]["task_ids"] = []
    elif mutation == "interface":
        data["interfaces"][0]["target"] = "missing"
    else:
        data["execution_profile"] = "shell"
    with pytest.raises(ValidationError):
        ProjectSpec.model_validate(data)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        "auth.json",
        "tests/test_new.py",
        "package.json",
        "requirements.txt",
        "CON.py",
        "C:/file.py",
        "src/.git/config",
        "a.py/b.py",
    ],
)
def test_unsafe_project_ownership(path):
    data = specification().model_dump()
    data["tasks"][0]["owned_files"] = [path]
    with pytest.raises(ValidationError):
        ProjectSpec.model_validate(data)


def test_dag_ready_selection():
    spec = specification()
    engine = DependencyEngine(spec)
    assert [t.id for t in engine.ready(spec.milestones[0], set(), 2)] == ["foundation", "utility"]
    assert not engine.ready(spec.milestones[1], {"foundation"}, 2)
    assert [t.id for t in engine.ready(spec.milestones[1], {"foundation", "utility"}, 2)] == [
        "application"
    ]


def test_real_parallel_dag_milestones_and_dependent_outputs(repo):
    models = ProjectModels()
    runner = ProjectChecks()
    original = git(repo, "rev-parse", "HEAD")
    instance = workflow(AutoDevConfig(), repo, models, runner)
    report = asyncio.run(instance.run_task("Build a composed repository"))
    assert report.succeeded, report.stopped_reason
    assert [m.status for m in report.milestones] == ["completed"] * 3
    starts = [e[2] for e in models.events if e[0] == "start" and e[1] in {"foundation", "utility"}]
    ends = [e[2] for e in models.events if e[0] == "end" and e[1] in {"foundation", "utility"}]
    assert max(starts) < min(ends)
    assert next(e[2] for e in models.events if e[:2] == ("start", "application")) > max(ends)
    assert next(e[2] for e in models.events if e[:2] == ("start", "documentation")) > next(
        e[2] for e in models.events if e[:2] == ("end", "application")
    )
    assert len({t.worktree for t in report.tasks}) == 4
    assert runner.calls[-1] is None  # Final validation uses the complete existing test suite.
    assert "tests/test_base.py" in runner.calls[1]  # Prerequisite tests remain in validation.
    assert "documentation" in (Path(report.integration_worktree) / "README.md").read_text()
    assert git(repo, "rev-parse", "HEAD") == original
    assert (repo / "README.md").read_text() == "Offline dashboard test fixture\n"
    assert len(report.checkpoint_history) >= 7


def paused(repo, models=None):
    models = models or ProjectModels()
    instance = workflow(AutoDevConfig(), repo, models)

    def observer(event):
        if event["stage"] == "developer_started":
            instance.request_pause()

    instance.observer = observer
    report = asyncio.run(instance.run_task("Build a composed repository"))
    assert report.integration_status == "paused"
    assert set(report.validated_tasks) == {"foundation", "utility"}
    return instance, report, models


def test_checkpoint_resume_never_repeats_validated_work(repo):
    old, report, models = paused(repo)
    instance = workflow(AutoDevConfig(), repo, models, run_id=report.run_id)
    resumed = asyncio.run(instance.run_task(report.request, resume=report))
    assert resumed.succeeded, resumed.stopped_reason
    assert models.calls.count("foundation") == models.calls.count("utility") == 1
    assert models.calls.count("application") == 1
    assert resumed.model_calls_reserved == 6  # Architect + four developers + reviewer.
    assert old.integration.run_id == instance.integration.run_id


@pytest.mark.parametrize(
    "changed",
    ["source", "integration", "task", "checkpoint", "configuration", "unsafe_boundary", "branch"],
)
def test_unsafe_recovery_is_rejected_without_overwriting(repo, changed):
    old, report, models = paused(repo)
    config = AutoDevConfig()
    if changed == "source":
        (repo / "README.md").write_text("uncommitted user work")
    elif changed == "integration":
        (old.integration.integration.path / "untracked.py").write_text("user work")
    elif changed == "task":
        (Path(report.tasks[0].worktree) / "base.py").write_text("user work")
    elif changed == "checkpoint":
        path = (
            old.integration.root
            / "checkpoints"
            / f"{report.checkpoint_history[-1].number:03d}.json"
        )
        data = json.loads(path.read_text())
        data["task_heads"] = {}
        path.write_text(json.dumps(data))
    elif changed == "configuration":
        config = AutoDevConfig(parallel=ParallelConfig(concurrency=1))
    elif changed == "branch":
        git(repo, "switch", "-c", "user-branch")
    else:
        report.checkpoint_safe = False
    before = list(models.calls)
    instance = workflow(config, repo, models, run_id=report.run_id)
    with pytest.raises(RecoveryRequired):
        asyncio.run(instance.run_task(report.request, resume=report))
    assert models.calls == before
    if changed == "source":
        assert (repo / "README.md").read_text() == "uncommitted user work"


def test_integration_conflict_stops_dependent_tasks(repo):
    instance = workflow(AutoDevConfig(), repo)
    instance.integration.integrate = AsyncMock(side_effect=IntegrationConflict(["base.py"]))
    report = asyncio.run(instance.run_task("Build a composed repository"))
    assert report.integration_status == "conflict"
    assert report.conflicts == ["base.py"]
    assert {t.task.id for t in report.tasks} == {"foundation", "utility"}
    assert not report.checkpoint_safe


def test_infrastructure_failure_does_not_request_corrections(repo):
    models, checks = ProjectModels(), ProjectChecks()
    checks.failure = CheckResult(
        command=["mock-pytest"], exit_code=1, failure_kind="infrastructure"
    )
    checks.failures_left = 100
    report = asyncio.run(workflow(AutoDevConfig(), repo, models, checks).run_task("Build project"))
    assert report.integration_status == "infrastructure_failed"
    assert len(models.calls) == 2


def test_bounded_project_corrections(repo):
    models, checks = ProjectModels(overlap=False), ProjectChecks()
    checks.failure = CheckResult(
        command=["mock-pytest"], exit_code=1, stdout="base.py: code failure"
    )
    checks.failures_left = 100
    report = asyncio.run(workflow(AutoDevConfig(), repo, models, checks).run_task("Build project"))
    assert report.integration_status == "checks_failed"
    assert models.calls.count("foundation") == 4
    assert models.calls.count("utility") == 1


def test_architect_rejects_nonexistent_tests():
    provider = AsyncMock()
    provider.architect.return_value = specification()
    with pytest.raises(ValueError, match="absent"):
        asyncio.run(ProjectArchitect(provider).design("Build project", []))


def test_configured_single_developer_executes_independent_tasks_serially(repo):
    models = ProjectModels(overlap=False)
    config = AutoDevConfig(parallel=ParallelConfig(concurrency=1))
    report = asyncio.run(workflow(config, repo, models).run_task("Build composed project"))
    assert report.succeeded
    first_end = next(e[2] for e in models.events if e[:2] == ("end", "foundation"))
    next_start = next(e[2] for e in models.events if e[:2] == ("start", "utility"))
    assert first_end < next_start


def test_global_model_call_limit_stops_later_tasks(repo):
    models = ProjectModels()
    config = AutoDevConfig(parallel=ParallelConfig(max_model_calls=3))
    report = asyncio.run(workflow(config, repo, models).run_task("Build composed project"))
    assert report.integration_status == "agent_failed"
    assert report.model_calls_reserved == 3
    assert set(models.calls) == {"foundation", "utility"}


def test_resume_cannot_reset_workflow_deadline(repo):
    _, report, models = paused(repo)
    report.duration_seconds = AutoDevConfig().parallel.workflow_timeout_seconds
    before = list(models.calls)
    instance = workflow(AutoDevConfig(), repo, models, run_id=report.run_id)
    result = asyncio.run(instance.run_task(report.request, resume=report))
    assert result.integration_status == "timed_out"
    assert models.calls == before


def test_boundary_interruption_recovers_without_repeating_work(repo):
    _, report, models = paused(repo)
    report.integration_status, report.finished_at = "integrated", ""
    instance = workflow(AutoDevConfig(), repo, models, run_id=report.run_id)
    result = asyncio.run(instance.run_task(report.request, resume=report))
    assert result.succeeded
    assert models.calls.count("foundation") == models.calls.count("utility") == 1


def test_user_edits_during_run_prevent_safe_checkpoint_and_are_preserved(repo):
    models = ProjectModels()
    instance = workflow(AutoDevConfig(), repo, models)

    def observe(event):
        if event["stage"] == "checks_finished":
            (repo / "README.md").write_text("uncommitted user changes")

    instance.observer = observe
    report = asyncio.run(instance.run_task("Build composed project"))
    assert not report.succeeded
    assert not report.checkpoint_safe
    assert models.calls == ["foundation", "utility"]
    assert (repo / "README.md").read_text() == "uncommitted user changes"
    assert len(report.checkpoint_history) == 1


def test_pause_requested_during_checkpoint_verification_is_honored(repo):
    instance = workflow(AutoDevConfig(), repo)
    save = instance.store.save

    async def saving(report):
        if report.validated_tasks:
            instance.request_pause()
        await save(report)

    instance.store.save = saving
    report = asyncio.run(instance.run_task("Build composed project"))
    assert report.integration_status == "paused"
    assert report.checkpoint_safe
    assert set(report.validated_tasks) == {"foundation", "utility"}


@pytest.mark.parametrize("path", ["../test.py", "tests/evil.py;whoami", "--override-ini=foo"])
def test_stage_check_paths_cannot_inject_commands(path):
    runner = SandboxChecks(AutoDevConfig())
    runner._blocking = AsyncMock()
    with pytest.raises(ValueError):
        asyncio.run(runner.run(Path.cwd(), [path]))
    runner._blocking.assert_not_awaited()


def test_stage_checks_keep_fixed_executable_and_options():
    runner = SandboxChecks(AutoDevConfig())
    runner._blocking = AsyncMock(return_value=CheckResult(command=["mock"], exit_code=0))
    result = asyncio.run(runner.run(Path.cwd(), ["tests/test_core.py"]))
    assert result.passed
    assert runner._blocking.await_args_list[1].args[2] == [
        "python",
        "-m",
        "pytest",
        "tests/test_core.py",
        "--tb=short",
        "-q",
    ]
