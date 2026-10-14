from __future__ import annotations

from pathlib import Path

from autodev.agents import (
    DeveloperAgent,
    ReviewerAgent,
)
from autodev.budget import ApiBudgetTracker, BudgetExceededError
from autodev.config import AutoDevConfig
from autodev.providers import build_provider
from autodev.runner import DEFAULT_PYTEST_COMMAND, TestRunner
from autodev.sandbox import DockerSandbox, DryRunSandbox, SandboxBackend
from autodev.schemas import AttemptLog, GeneratedFile, ReviewResult, TestRunResult, WorkflowResult
from autodev.workspace import Workspace, WorkspaceViolation


class Orchestrator:
    def __init__(
        self,
        config: AutoDevConfig,
        developer: DeveloperAgent,
        reviewer: ReviewerAgent,
        test_runner: TestRunner,
        budget: ApiBudgetTracker,
    ) -> None:
        self._config = config
        self._developer = developer
        self._reviewer = reviewer
        self._test_runner = test_runner
        self._budget = budget

    async def run_task(self, task: str, seed_tests_dir: Path | None = None) -> WorkflowResult:
        workspace = Workspace(self._config.workspace_dir)
        if self._config.reset_workspace:
            workspace.clear()
        if seed_tests_dir:
            workspace.copy_tree_into(seed_tests_dir, "tests")

        attempts: list[AttemptLog] = []
        previous_files: list[GeneratedFile] = workspace.snapshot_files()
        failure_output: str | None = None
        stopped_reason = "max iterations reached"
        final_test_result: TestRunResult | None = None

        for iteration in range(1, self._config.agents.max_iterations + 1):
            try:
                generated = await self._developer.generate(task, previous_files, failure_output)
            except BudgetExceededError as exc:
                stopped_reason = str(exc)
                break

            try:
                workspace.write_generated_files(generated.files, protected_prefixes=("tests",))
            except WorkspaceViolation as exc:
                final_test_result = TestRunResult(
                    command=DEFAULT_PYTEST_COMMAND,
                    exit_code=None,
                    skipped=True,
                    reason=str(exc),
                )
                attempts.append(
                    AttemptLog(
                        iteration=iteration,
                        generated=generated,
                        test_result=final_test_result,
                    )
                )
                stopped_reason = str(exc)
                break
            previous_files = workspace.snapshot_files()
            final_test_result = self._test_runner.run(workspace.root)
            attempts.append(
                AttemptLog(
                    iteration=iteration,
                    generated=generated,
                    test_result=final_test_result,
                )
            )

            if final_test_result.passed:
                stopped_reason = "tests passed"
                break
            if final_test_result.skipped:
                stopped_reason = final_test_result.reason or "test execution skipped"
                break
            failure_output = final_test_result.combined_output()

        review = await self._review_final(task, workspace, final_test_result)
        tests_passed = final_test_result.passed if final_test_result else False
        succeeded = bool(tests_passed and review and review.approved)
        if review is None and tests_passed:
            stopped_reason = "review skipped because API budget was exhausted"
        elif tests_passed and not review.approved:
            stopped_reason = "review did not approve final implementation"

        return WorkflowResult(
            task=task,
            succeeded=succeeded,
            attempts=attempts,
            review=review,
            workspace=str(workspace.root),
            stopped_reason=stopped_reason,
            model_calls_reserved=self._budget.calls_reserved,
        )

    async def _review_final(
        self,
        task: str,
        workspace: Workspace,
        final_test_result: TestRunResult | None,
    ) -> ReviewResult | None:
        try:
            return await self._reviewer.review(task, workspace.snapshot_files(), final_test_result)
        except BudgetExceededError:
            return None


def build_orchestrator(config: AutoDevConfig) -> Orchestrator:
    provider = build_provider(config)
    budget = ApiBudgetTracker(
        budget_usd=config.agents.api_budget_usd,
        estimated_cost_per_model_call_usd=config.agents.estimated_cost_per_model_call_usd,
    )
    sandbox = build_sandbox(config)
    test_runner = TestRunner(
        sandbox=sandbox,
        timeout_seconds=config.sandbox.timeout_seconds,
        max_output_chars=config.sandbox.max_output_chars,
    )
    developer = DeveloperAgent(
        provider,
        budget=budget,
    )
    reviewer = ReviewerAgent(
        provider,
        budget=budget,
    )
    return Orchestrator(
        config=config,
        developer=developer,
        reviewer=reviewer,
        test_runner=test_runner,
        budget=budget,
    )


def build_sandbox(config: AutoDevConfig) -> SandboxBackend:
    if config.sandbox.backend == "docker":
        return DockerSandbox(image=config.sandbox.docker_image)
    return DryRunSandbox()
