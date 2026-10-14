import asyncio
import shutil
import subprocess
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from autodev.agents import ReviewerAgent
from autodev.budget import ApiBudgetTracker
from autodev.config import AutoDevConfig
from autodev.integration import GitOperationError, IntegrationConflict, IntegrationManager
from autodev.parallel import ParallelOrchestrator
from autodev.parallel_schemas import IntegratedChecks
from autodev.planning import DevelopmentTask, TaskPlan, TaskPlanner
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as RunResult
from autodev.workspace import Workspace, WorkspaceViolation


def run_git(repo, *args):
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={repo.as_posix()}",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("Git is required for offline worktree integration tests")
    root = tmp_path / "repository"
    root.mkdir()
    run_git(root, "init", "--initial-branch=main")
    (root / ".gitignore").write_text(".autodev/\n.env\n")
    (root / "module0.py").write_text("value = 0\n")
    (root / "module1.py").write_text("value = 0\n")
    (root / "tests").mkdir()
    (root / "tests/test_fixed.py").write_text("assert True\n")
    run_git(root, "add", ".gitignore", "module0.py", "module1.py", "tests/test_fixed.py")
    run_git(root, "commit", "-m", "baseline")
    (root / "user_notes.txt").write_text("user-owned untracked content")
    (root / ".env").write_text("SYNTHETIC_TEST_SENTINEL=never-copy\n")
    return root


def task(identifier, path):
    return DevelopmentTask(
        id=identifier,
        description="Change value",
        owned_files=[path],
        acceptance_criteria=["value is correct"],
    )


def generated(path, value):
    return CodeGenerationResult(
        summary="update", files=[GeneratedFile(path=path, content=f"value = {value}\n")]
    )


def test_real_git_worktrees_commits_integration_and_source_preservation(repo):
    original_head = run_git(repo, "rev-parse", "HEAD")
    manager = IntegrationManager(repo)
    first, second = task("first", "module0.py"), task("second", "module1.py")

    async def exercise():
        await manager.prepare()
        tree1 = await manager.create_task(first)
        tree2 = await manager.create_task(second)
        assert tree1.path != tree2.path and tree1.branch != tree2.branch
        assert (tree1.path / ".git").is_file()
        assert not (tree1.path / ".env").exists()
        assert not (tree1.path / "user_notes.txt").exists()
        manager.apply(first, generated("module0.py", 1))
        manager.apply(second, generated("module1.py", 2))
        commits = await asyncio.gather(
            manager.commit_task(first, 1), manager.commit_task(second, 1)
        )
        for commit in commits:
            await manager.integrate(commit)
        # A correction commit applies as a delta over that task's preceding commit.
        manager.apply(first, generated("module0.py", 3))
        correction = await manager.commit_task(first, 2)
        await manager.integrate(correction)
        assert (manager.integration.path / "module0.py").read_text() == "value = 3\n"
        assert (manager.integration.path / "module1.py").read_text() == "value = 2\n"
        assert (tree1.path / "module1.py").read_text() == "value = 0\n"
        assert (manager.integration.path / "tests/test_fixed.py").read_text() == "assert True\n"
        assert (await manager.git(manager.integration.path, "branch", "--show-current")) == (
            manager.integration.branch
        )

    asyncio.run(exercise())
    assert run_git(repo, "branch", "--show-current") == "main"
    assert run_git(repo, "rev-parse", "HEAD") == original_head
    assert (repo / "module0.py").read_text() == "value = 0\n"
    assert (repo / "user_notes.txt").read_text() == "user-owned untracked content"
    assert run_git(repo, "status", "--porcelain", "--untracked-files=no") == ""


def test_real_conflict_is_detected_without_reset_or_abort(repo):
    manager = IntegrationManager(repo)
    owner = task("owner", "module0.py")

    async def exercise():
        await manager.prepare()
        await manager.create_task(owner)
        manager.apply(owner, generated("module0.py", 1))
        commit = await manager.commit_task(owner, 1)
        Workspace(manager.integration.path).write_generated_files(generated("module0.py", 99).files)
        await manager.git(manager.integration.path, "add", "--", "module0.py")
        await manager.git(manager.integration.path, "commit", "-m", "Simulated competing change")
        with pytest.raises(IntegrationConflict) as conflict:
            await manager.integrate(commit)
        assert conflict.value.paths == ["module0.py"]
        assert await manager.git(manager.integration.path, "diff", "--name-only", "--diff-filter=U")

    asyncio.run(exercise())
    assert run_git(repo, "branch", "--show-current") == "main"
    assert manager.integration.path.exists()


def test_scope_and_incomplete_output_rejected_atomically(repo):
    manager = IntegrationManager(repo)
    owner = task("owner", "module0.py")

    async def exercise():
        await manager.prepare()
        tree = await manager.create_task(owner)
        malicious = generated("module0.py", 5)
        malicious.files.append(GeneratedFile(path="module1.py", content="tampered"))
        for result in (malicious, CodeGenerationResult(summary="missing", files=[])):
            with pytest.raises(WorkspaceViolation):
                manager.apply(owner, result)
        assert (tree.path / "module0.py").read_text() == "value = 0\n"
        assert (tree.path / "module1.py").read_text() == "value = 0\n"
        # A change introduced outside the trusted write gate is also blocked at commit.
        (tree.path / "module1.py").write_text("outside scope\n")
        with pytest.raises(WorkspaceViolation, match="outside assigned scope"):
            await manager.commit_task(owner, 1)

    asyncio.run(exercise())


def test_dirty_source_checkout_is_refused_without_changes(repo):
    (repo / "module0.py").write_text("user edits\n")
    manager = IntegrationManager(repo)
    with pytest.raises(GitOperationError, match="tracked changes"):
        asyncio.run(manager.prepare())
    assert not manager.root.exists()
    assert (repo / "module0.py").read_text() == "user edits\n"


def test_git_filters_require_review_before_checkout_or_staging(repo):
    # Attribute without a configured command: no untrusted filter is executed by this fixture.
    (repo / ".gitattributes").write_text("module0.py filter=custom\n")
    run_git(repo, "add", ".gitattributes")
    run_git(repo, "commit", "-m", "filter fixture")
    manager = IntegrationManager(repo)
    with pytest.raises(GitOperationError, match="drivers require explicit review"):
        asyncio.run(manager.prepare())
    assert not manager.root.exists()


def test_tracked_credential_paths_are_not_copied_into_worktrees(repo):
    run_git(repo, "add", "--force", ".env")
    run_git(repo, "commit", "-m", "synthetic unsafe fixture")
    manager = IntegrationManager(repo)
    with pytest.raises(GitOperationError, match="credential path"):
        asyncio.run(manager.prepare())
    assert not manager.root.exists()


def test_seed_tests_are_committed_only_in_integration_branch(repo, tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "test_acceptance.py").write_text("assert True\n")
    manager = IntegrationManager(repo)

    async def exercise():
        await manager.prepare()
        commit = await manager.seed_tests(seed)
        assert len(commit) == 40
        assert (manager.integration.path / "tests/test_acceptance.py").exists()
        with pytest.raises(WorkspaceViolation, match="new Python test files"):
            await manager.seed_tests(seed)

    asyncio.run(exercise())
    assert not (repo / "tests/test_acceptance.py").exists()


def test_git_hooks_do_not_execute_in_workflow(repo):
    hook = repo / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 99\n")
    hook.chmod(0o755)
    manager = IntegrationManager(repo)
    owner = task("owner", "module0.py")

    async def exercise():
        await manager.prepare()
        await manager.create_task(owner)
        manager.apply(owner, generated("module0.py", 1))
        assert await manager.commit_task(owner, 1)

    asyncio.run(exercise())


def test_offline_parallel_workflow_with_real_worktrees_and_correction(repo):
    manager = IntegrationManager(repo)
    plan = TaskPlan(
        summary="two", tasks=[task("first", "module0.py"), task("second", "module1.py")]
    )
    barrier = asyncio.Event()
    active = 0
    peak = 0
    model_calls = {"first": 0, "second": 0}

    def factory(worktree):
        name = worktree.name

        class Client:
            async def generate_code(self, prompt, context, failure):
                nonlocal active, peak
                model_calls[name] += 1
                active += 1
                peak = max(peak, active)
                if active == 2:
                    barrier.set()
                await asyncio.wait_for(barrier.wait(), 1)
                await asyncio.sleep(0.02)
                active -= 1
                if name == "first":
                    value = 1 if model_calls[name] == 1 else 3
                    return generated("module0.py", value)
                return generated("module1.py", 2)

        return Client()

    async def validate(worktree):
        assert (worktree / "module1.py").read_text() == "value = 2\n"
        passed = (worktree / "module0.py").read_text() == "value = 3\n"
        return IntegratedChecks(
            pytest=RunResult(
                command=["pytest"],
                exit_code=0 if passed else 1,
                stdout="passed" if passed else "module0.py:1: wrong value",
            ),
            ruff=RunResult(command=["ruff"], exit_code=0),
        )

    budget = ApiBudgetTracker(Decimal("10"), Decimal("0.05"))
    reviewer = AsyncMock()
    reviewer.review.return_value = ReviewResult(approved=True, risk_level="low", summary="OK")
    runner = AsyncMock()
    runner.run.side_effect = validate
    orchestrator = ParallelOrchestrator(
        AutoDevConfig(),
        TaskPlanner(AsyncMock()),
        factory,
        ReviewerAgent(reviewer, budget),
        manager,
        runner,
        budget,
    )
    report = asyncio.run(orchestrator.run_task("two modules", plan=plan))
    assert report.succeeded
    assert peak == 2
    assert model_calls == {"first": 2, "second": 1}
    assert [len(result.attempts) for result in report.tasks] == [2, 1]
    assert len(report.rounds) == 2
    assert report.integration_commit == run_git(manager.integration.path, "rev-parse", "HEAD")
    assert run_git(repo, "branch", "--show-current") == "main"
    assert (repo / "module0.py").read_text() == "value = 0\n"
