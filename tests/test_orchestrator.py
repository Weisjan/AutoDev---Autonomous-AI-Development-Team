import asyncio
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from autodev.agents import DeveloperAgent, ReviewerAgent
from autodev.budget import ApiBudgetTracker
from autodev.config import AgentConfig, AutoDevConfig, SandboxConfig
from autodev.orchestrator import Orchestrator
from autodev.runner import DEFAULT_PYTEST_COMMAND
from autodev.runner import TestRunner as PytestRunner
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as RunResult


class FakeDeveloperClient:
    def __init__(self) -> None:
        self.calls = 0
        self.received_failures: list[str | None] = []

    async def generate_code(
        self,
        task: str,
        previous_files: list[GeneratedFile],
        test_output: str | None,
    ) -> CodeGenerationResult:
        _ = task, previous_files
        self.calls += 1
        self.received_failures.append(test_output)
        if self.calls == 1:
            content = "def add(a, b):\n    return a - b\n"
        else:
            content = "def add(a, b):\n    return a + b\n"
        return CodeGenerationResult(
            summary=f"attempt {self.calls}",
            files=[GeneratedFile(path="calculator.py", content=content)],
        )


class FakeReviewerClient:
    async def review(
        self,
        task: str,
        files: list[GeneratedFile],
        test_result: RunResult | None,
    ) -> ReviewResult:
        _ = task, files, test_result
        return ReviewResult(approved=True, risk_level="low", summary="looks good", findings=[])


class SequenceSandbox:
    def __init__(self) -> None:
        self.calls = 0
        self.commands: list[list[str]] = []

    def run_pytest(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> RunResult:
        _ = workspace, timeout_seconds, max_output_chars
        self.calls += 1
        self.commands.append(list(command))
        if self.calls == 1:
            return RunResult(command=list(command), exit_code=1, stdout="assert -1 == 3")
        return RunResult(command=list(command), exit_code=0, stdout="1 passed")


def test_orchestrator_repairs_after_failed_tests(tmp_path: Path) -> None:
    budget = ApiBudgetTracker(
        budget_usd=Decimal("1.00"),
        estimated_cost_per_model_call_usd=Decimal("0.01"),
    )
    developer_client = FakeDeveloperClient()
    sandbox = SequenceSandbox()
    config = AutoDevConfig(
        workspace_dir=tmp_path / "workspace",
        agents=AgentConfig(max_iterations=3),
        sandbox=SandboxConfig(),
    )
    orchestrator = Orchestrator(
        config=config,
        developer=DeveloperAgent(developer_client, budget),
        reviewer=ReviewerAgent(FakeReviewerClient(), budget),
        test_runner=PytestRunner(sandbox=sandbox),
        budget=budget,
    )

    result = asyncio.run(orchestrator.run_task("Implement add(a, b)."))

    assert result.succeeded
    assert result.stopped_reason == "tests passed"
    assert len(result.attempts) == 2
    assert developer_client.received_failures[0] is None
    assert "assert -1 == 3" in (developer_client.received_failures[1] or "")
    assert sandbox.commands == [DEFAULT_PYTEST_COMMAND, DEFAULT_PYTEST_COMMAND]
    assert result.model_calls_reserved == 3


def test_sequential_infrastructure_failure_does_not_retry_or_review(tmp_path):
    class InfrastructureSandbox(SequenceSandbox):
        def run_pytest(self, workspace, command, timeout_seconds, max_output_chars):
            return RunResult(
                command=list(command),
                exit_code=2,
                failure_kind="infrastructure",
                stderr="ModuleNotFoundError: No module named 'pydantic'",
                reason="rebuild sandbox image",
            )

    budget = ApiBudgetTracker(Decimal("1"), Decimal("0.01"))
    developer_client = FakeDeveloperClient()
    config = AutoDevConfig(workspace_dir=tmp_path / "workspace")
    orchestrator = Orchestrator(
        config,
        DeveloperAgent(developer_client, budget),
        ReviewerAgent(FakeReviewerClient(), budget),
        PytestRunner(InfrastructureSandbox()),
        budget,
    )
    result = asyncio.run(orchestrator.run_task("Implement add"))
    assert not result.succeeded
    assert developer_client.calls == 1
    assert result.review is None
    assert result.model_calls_reserved == 1
    assert result.stopped_reason == "rebuild sandbox image"
