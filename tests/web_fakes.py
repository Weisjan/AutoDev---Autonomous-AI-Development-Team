"""Offline dashboard fixtures. Never imported by the production web application."""

import asyncio
import subprocess
from decimal import Decimal

from autodev.agents import ReviewerAgent
from autodev.budget import ApiBudgetTracker
from autodev.integration import IntegrationManager
from autodev.parallel import ParallelOrchestrator
from autodev.parallel_schemas import IntegratedChecks
from autodev.planning import DevelopmentTask, TaskPlan, TaskPlanner
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as CheckResult


def git(root, *args):
    return subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "-c",
            "user.name=Dashboard Test",
            "-c",
            "user.email=test@localhost",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
    ).stdout.strip()


def repository(root):
    root.mkdir(parents=True)
    git(root, "init", "--initial-branch=main")
    (root / ".gitignore").write_text(".autodev/\n", encoding="utf-8")
    (root / "README.md").write_text("Offline dashboard test fixture\n", encoding="utf-8")
    git(root, "add", ".gitignore", "README.md")
    git(root, "commit", "-m", "Test baseline")
    return root


class MockProvider:
    async def plan(self, request, files, max_tasks):
        await asyncio.sleep(0.05)
        return TaskPlan(
            summary="Two independent offline test modules",
            tasks=[
                DevelopmentTask(
                    id=f"module{i}",
                    description=f"Implement module {i}",
                    owned_files=[f"module{i}.py"],
                    acceptance_criteria=[f"value equals {i}"],
                )
                for i in range(2)
            ],
        )

    async def generate_code(self, prompt, context, failure):
        await asyncio.sleep(0.35)
        i = 0 if "module0.py" in prompt else 1
        return CodeGenerationResult(
            summary="Offline fixture",
            files=[GeneratedFile(path=f"module{i}.py", content=f"value = {i}\n")],
        )

    async def review(self, task, files, test_result):
        return ReviewResult(approved=True, risk_level="low", summary="Offline fixture approved")


class MockChecks:
    async def run(self, workspace):
        # These are deterministic mock checks, never represented as a real Docker run.
        assert (workspace / "module0.py").read_text() == "value = 0\n"
        assert (workspace / "module1.py").read_text() == "value = 1\n"
        return IntegratedChecks(
            pytest=CheckResult(
                command=["mock-pytest"],
                exit_code=0,
                stdout="OFFLINE TEST FIXTURE: both generated modules validated",
            ),
            ruff=CheckResult(command=["mock-ruff"], exit_code=0, stdout="OFFLINE TEST FIXTURE"),
        )


def workflow_factory(config, root):
    provider = MockProvider()
    budget = ApiBudgetTracker(Decimal("10"), Decimal("0.05"))
    return ParallelOrchestrator(
        config,
        TaskPlanner(provider),
        lambda _: provider,
        ReviewerAgent(provider, budget),
        IntegrationManager(root),
        MockChecks(),
        budget,
    )
