"""Offline project fixtures: real Git, mocked model and Docker results only."""

import asyncio
from time import monotonic

from web_fakes import git, repository

from autodev.agents import ReviewerAgent
from autodev.architect import ProjectArchitect
from autodev.budget import ApiBudgetTracker
from autodev.integration import IntegrationManager, TaskWorktree
from autodev.parallel_schemas import IntegratedChecks
from autodev.project import ProjectOrchestrator
from autodev.project_models import ProjectSpec
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as CheckResult


def specification():
    tasks = [
        dict(
            id="foundation",
            description="Implement the base module",
            owned_files=["base.py"],
            acceptance_criteria=["value = 1"],
            depends_on=[],
            test_paths=["tests/test_base.py"],
        ),
        dict(
            id="utility",
            description="Implement an independent utility",
            owned_files=["utility.py"],
            acceptance_criteria=["value = 2"],
            depends_on=[],
            test_paths=["tests/test_utility.py"],
        ),
        dict(
            id="application",
            description="Compose base and utility",
            owned_files=["app.py", "README.md"],
            acceptance_criteria=["uses both dependencies"],
            depends_on=["foundation", "utility"],
            test_paths=["tests/test_app.py"],
        ),
        dict(
            id="documentation",
            description="Finish repository documentation",
            owned_files=["README.md"],
            acceptance_criteria=["Documents integrated project"],
            depends_on=["application"],
            test_paths=["tests/test_app.py"],
        ),
    ]
    return ProjectSpec(
        title="Offline composed project",
        summary="Build a repository in three validated milestones",
        technology_stack=["Python"],
        repository_structure=["base.py", "utility.py", "app.py", "README.md"],
        components=[
            dict(
                id="core",
                responsibility="Provide base and utility",
                files=["base.py", "utility.py"],
            ),
            dict(
                id="application",
                responsibility="Compose the core and document it",
                files=["app.py", "README.md"],
            ),
        ],
        interfaces=[
            dict(source="core", target="application", contract="base.value + utility.value = 3")
        ],
        tasks=tasks,
        milestones=[
            dict(
                id=name,
                description=name,
                task_ids=ids,
                acceptance_criteria=["Trusted tests pass"],
                test_paths=paths,
            )
            for name, ids, paths in [
                (
                    "core",
                    ["foundation", "utility"],
                    ["tests/test_base.py", "tests/test_utility.py"],
                ),
                ("application", ["application"], ["tests/test_app.py"]),
                ("documentation", ["documentation"], ["tests/test_app.py"]),
            ]
        ],
        acceptance_criteria=["Composed repository passes tests and review"],
        testing_requirements=["Run existing trusted Python tests in Docker"],
        risks=["Mock validation in tests only"],
        assumptions=["Dependencies and tests exist in the baseline"],
    )


def project_repository(root):
    repository(root)
    tests = root / "tests"
    tests.mkdir()
    for name in ("base", "utility", "app"):
        (tests / f"test_{name}.py").write_text("def test_trusted_fixture():\n    assert True\n")
    git(root, "add", "tests")
    git(root, "commit", "-m", "Trusted fixture tests")
    return root


class ProjectModels:
    def __init__(self, overlap=True):
        self.plan = specification()
        self.events, self.calls = [], []
        self.overlap = overlap
        self.barrier = asyncio.Event()
        self.entered = 0
        self.error = None
        self.delay = 0

    def client(self, path):
        controller = self

        class Client:
            async def architect(self, request, files, max_tasks):
                return controller.plan

            async def generate_code(self, prompt, context, feedback):
                task_id = path.name
                task = next(t for t in controller.plan.tasks if t.id == task_id)
                controller.calls.append(task_id)
                controller.events.append(("start", task_id, monotonic()))
                if task_id in {"foundation", "utility"} and controller.overlap:
                    controller.entered += 1
                    if controller.entered >= 2:
                        controller.barrier.set()
                    await asyncio.wait_for(controller.barrier.wait(), 3)
                    await asyncio.sleep(0.03)
                if task_id == "application":
                    assert (path / "base.py").read_text() == "value = 1\n"
                    assert (path / "utility.py").read_text() == "value = 2\n"
                    assert {f.path for f in context} >= {"base.py", "utility.py"}
                if task_id == "documentation":
                    assert "from base import" in (path / "app.py").read_text()
                if controller.error:
                    raise controller.error
                await asyncio.sleep(controller.delay)
                contents = {
                    "base.py": "value = 1\n",
                    "utility.py": "value = 2\n",
                    "app.py": (
                        "from base import value as base\n"
                        "from utility import value as utility\n"
                        "result = base + utility\n"
                    ),
                    "README.md": f"# Project\nImplemented by {task_id}\n",
                }
                controller.events.append(("end", task_id, monotonic()))
                return CodeGenerationResult(
                    summary="Offline fixture",
                    files=[GeneratedFile(path=p, content=contents[p]) for p in task.owned_files],
                )

            async def review(self, task, files, test_result):
                return ReviewResult(
                    approved=True, risk_level="low", summary="Offline project fixture approved"
                )

        return Client()


class ProjectChecks:
    def __init__(self):
        self.calls = []
        self.failure = None
        self.failures_left = 0

    async def run(self, workspace, test_paths=None):
        self.calls.append(test_paths)
        failed = self.failures_left > 0
        self.failures_left -= 1
        result = self.failure if failed else None
        return IntegratedChecks(
            pytest=result
            or CheckResult(
                command=["mock-pytest"],
                exit_code=0,
                stdout="OFFLINE FIXTURE: selected project tests passed",
            ),
            ruff=CheckResult(command=["mock-ruff"], exit_code=0, stdout="OFFLINE FIXTURE"),
        )


def workflow(config, repo, models=None, checks=None, run_id=None):
    models, checks = models or ProjectModels(), checks or ProjectChecks()
    manager = IntegrationManager(repo)
    if run_id:
        manager.run_id, manager.root = run_id, repo / ".autodev/runs" / run_id
        manager.integration = TaskWorktree(
            manager.root / "integration", f"autodev/{run_id}/integration"
        )
    client = models.client(manager.integration.path)
    budget = ApiBudgetTracker(
        config.agents.api_budget_usd, config.agents.estimated_cost_per_model_call_usd
    )
    return ProjectOrchestrator(
        config,
        None,
        models.client,
        ReviewerAgent(client, budget),
        manager,
        checks,
        budget,
        architect=ProjectArchitect(client, config.parallel.max_tasks),
    )
