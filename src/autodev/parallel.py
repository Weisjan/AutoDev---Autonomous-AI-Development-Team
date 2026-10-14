from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Protocol

from pydantic import ValidationError

from autodev.agents import DeveloperAgent, DeveloperModelClient, ReviewerAgent
from autodev.budget import ApiBudgetTracker, BudgetExceededError
from autodev.config import AutoDevConfig
from autodev.integration import GitOperationError, IntegrationConflict, IntegrationManager
from autodev.parallel_schemas import (
    AgentAttempt,
    IntegratedChecks,
    IntegrationRound,
    ParallelTaskResult,
    ParallelWorkflowReport,
)
from autodev.planning import TaskPlan, TaskPlanner, responsible_tasks
from autodev.providers import CodexCLIProvider, ProviderError
from autodev.runner import DEFAULT_PYTEST_COMMAND
from autodev.sandbox import DockerSandbox, DryRunSandbox
from autodev.schemas import CodeGenerationResult, GeneratedFile
from autodev.workspace import Workspace, WorkspaceViolation


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class CheckRunner(Protocol):
    async def run(self, workspace: Path) -> IntegratedChecks: ...


class SandboxChecks:
    def __init__(self, config: AutoDevConfig) -> None:
        self.config = config
        self.sandbox = (
            DockerSandbox(config.sandbox.docker_image)
            if config.sandbox.backend == "docker"
            else DryRunSandbox()
        )

    async def run(self, workspace: Path) -> IntegratedChecks:
        pytest = await asyncio.to_thread(
            self.sandbox.run_pytest,
            workspace,
            DEFAULT_PYTEST_COMMAND,
            self.config.sandbox.timeout_seconds,
            self.config.sandbox.max_output_chars,
        )
        ruff = await asyncio.to_thread(
            self.sandbox.run_ruff,
            workspace,
            self.config.sandbox.timeout_seconds,
            self.config.sandbox.max_output_chars,
        )
        return IntegratedChecks(pytest=pytest, ruff=ruff)


class ParallelOrchestrator:
    def __init__(
        self,
        config: AutoDevConfig,
        planner: TaskPlanner,
        developer_factory: Callable[[Path], DeveloperModelClient],
        reviewer: ReviewerAgent,
        integration: IntegrationManager,
        checks: CheckRunner,
        budget: ApiBudgetTracker,
    ) -> None:
        self.config = config
        self.planner = planner
        self.developer_factory = developer_factory
        self.reviewer = reviewer
        self.integration = integration
        self.checks = checks
        self.budget = budget
        self.calls = 0

    def reserve_call(self) -> None:
        if self.calls >= self.config.parallel.max_model_calls:
            raise BudgetExceededError("parallel model-call limit reached")
        self.calls += 1

    async def run_task(
        self,
        request: str,
        seed_tests_dir: Path | None = None,
        plan: TaskPlan | None = None,
    ) -> ParallelWorkflowReport:
        start = monotonic()
        report = ParallelWorkflowReport(
            request=request,
            run_id=self.integration.run_id,
            started_at=timestamp(),
            integration_branch=self.integration.integration.branch,
            integration_worktree=str(self.integration.integration.path),
        )
        try:
            await asyncio.wait_for(
                self._run(report, seed_tests_dir, plan),
                self.config.parallel.workflow_timeout_seconds,
            )
        except IntegrationConflict as exc:
            report.integration_status = "conflict"
            report.conflicts = exc.paths
            report.stopped_reason = str(exc)
        except TimeoutError:
            report.integration_status = "timed_out"
            report.stopped_reason = "parallel workflow deadline exceeded"
        except (ProviderError, BudgetExceededError, GitOperationError, WorkspaceViolation) as exc:
            report.integration_status = "failed"
            report.stopped_reason = str(exc)
        except (ValidationError, ValueError):
            report.integration_status = "failed"
            report.stopped_reason = "invalid or incomplete task plan/agent output"
        except Exception:
            # Do not log untrusted exception payloads or provider diagnostics.
            report.integration_status = "failed"
            report.stopped_reason = (
                "unexpected workflow failure; retained worktrees need inspection"
            )
        finally:
            report.finished_at = timestamp()
            report.duration_seconds = monotonic() - start
            report.model_calls_reserved = self.calls
            if self.integration.created:
                path = self.integration.root / "report.json"
                report.report_path = str(path)
                path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return report

    async def _run(
        self,
        report: ParallelWorkflowReport,
        seed: Path | None,
        plan: TaskPlan | None,
    ) -> None:
        await self.integration.prepare()
        report.source_branch = self.integration.source_branch
        report.base_commit = self.integration.base_commit
        report.integration_commit = self.integration.base_commit
        if seed:
            report.seed_commit = await self.integration.seed_tests(seed)
            report.integration_commit = report.seed_commit
        context = Workspace(self.integration.integration.path).snapshot_files()
        if plan is None:
            self.reserve_call()
            self.budget.reserve_call("task planning")
            report.planner_execution = AgentAttempt(
                number=1, agent_id="planner", started_at=timestamp()
            )
            planning_start = monotonic()
            try:
                plan = await asyncio.wait_for(
                    self.planner.decompose(report.request, context),
                    self.config.parallel.agent_timeout_seconds,
                )
            finally:
                report.planner_execution.finished_at = timestamp()
                report.planner_execution.duration_seconds = monotonic() - planning_start
        plan = TaskPlan.model_validate(plan)
        if len(plan.tasks) > self.config.parallel.max_tasks:
            raise ValueError("plan exceeds configured task count")
        report.plan = plan
        for task in plan.tasks:
            tree = await self.integration.create_task(task)
            report.tasks.append(
                ParallelTaskResult(task=task, branch=tree.branch, worktree=str(tree.path))
            )

        pending = {task.id for task in plan.tasks}
        feedback: str | None = None
        for number in range(self.config.parallel.max_corrections + 1):
            current = IntegrationRound(number=number)
            report.rounds.append(current)
            selected = [result for result in report.tasks if result.task.id in pending]
            await self._develop(selected, report.request, context, feedback)
            if any(result.status != "completed" for result in selected):
                report.integration_status = "agent_failed"
                report.stopped_reason = "one or more agents failed; batch was not integrated"
                return
            for result in selected:
                commit = result.attempts[-1].commit
                if commit:
                    report.integration_commit = await self.integration.integrate(commit)
                    current.commits.append(report.integration_commit)
            report.integration_status = "integrated"
            current.checks = await self.checks.run(self.integration.integration.path)
            if current.checks.unavailable:
                report.integration_status = "validation_unavailable"
                report.stopped_reason = (
                    "pytest or Ruff execution unavailable; success cannot be verified"
                )
                return
            if current.checks.passed:
                self.reserve_call()
                context = Workspace(self.integration.integration.path).snapshot_files()
                report.reviewer_execution = AgentAttempt(
                    number=1, agent_id="reviewer", started_at=timestamp()
                )
                review_start = monotonic()
                try:
                    report.review = await asyncio.wait_for(
                        self.reviewer.review(report.request, context, current.checks.pytest),
                        self.config.parallel.agent_timeout_seconds,
                    )
                finally:
                    report.reviewer_execution.finished_at = timestamp()
                    report.reviewer_execution.duration_seconds = monotonic() - review_start
                report.succeeded = report.review.approved
                report.integration_status = "reviewed" if report.succeeded else "review_rejected"
                report.stopped_reason = (
                    "checks passed and review approved" if report.succeeded else "review rejected"
                )
                return
            feedback = current.checks.failure_output()
            pending = responsible_tasks(plan, feedback)
            current.correction_tasks = sorted(pending)
            context = Workspace(self.integration.integration.path).snapshot_files()
        report.integration_status = "checks_failed"
        report.stopped_reason = "bounded correction limit reached"

    async def _develop(
        self,
        results: list[ParallelTaskResult],
        request: str,
        context: list[GeneratedFile],
        feedback: str | None,
    ) -> None:
        slots: asyncio.Queue[str] = asyncio.Queue()
        for index in range(self.config.parallel.concurrency):
            slots.put_nowait(f"developer-{index + 1}")

        async def develop(result: ParallelTaskResult) -> None:
            agent_id = await slots.get()
            start = monotonic()
            attempt = AgentAttempt(
                number=len(result.attempts) + 1, agent_id=agent_id, started_at=timestamp()
            )
            result.attempts.append(attempt)
            result.status = "running"
            try:
                self.reserve_call()
                client = self.developer_factory(Path(result.worktree))
                developer = DeveloperAgent(client, self.budget)
                prompt = (
                    f"Overall request: {request}\nAssigned task: {result.task.description}\n"
                    f"Owned files (exact): {result.task.owned_files}\n"
                    f"Acceptance criteria: {result.task.acceptance_criteria}\n"
                    "Return every owned file exactly once. Return no other files. "
                    "Other files are read-only context. Do not run commands."
                )
                generated = await asyncio.wait_for(
                    developer.generate(prompt, context, feedback),
                    self.config.parallel.agent_timeout_seconds,
                )
                generated = CodeGenerationResult.model_validate(generated)
                self.integration.apply(result.task, generated)
                attempt.commit = await self.integration.commit_task(result.task, attempt.number)
                result.status = "completed"
            except asyncio.CancelledError:
                result.status = "cancelled"
                attempt.error = "agent cancelled by workflow deadline or caller"
                raise
            except TimeoutError:
                result.status = "failed"
                attempt.error = "agent deadline exceeded"
            except (
                ProviderError,
                BudgetExceededError,
                GitOperationError,
                WorkspaceViolation,
            ) as exc:
                result.status = "failed"
                attempt.error = str(exc)
            except (ValidationError, ValueError):
                result.status = "failed"
                attempt.error = "invalid or incomplete agent output"
            except Exception:
                result.status = "failed"
                attempt.error = "unexpected agent failure"
            finally:
                attempt.finished_at = timestamp()
                attempt.duration_seconds = monotonic() - start
                slots.put_nowait(agent_id)

        # TaskGroup waits for all started children and cancels them on workflow cancellation.
        async with asyncio.TaskGroup() as group:
            for result in results:
                group.create_task(develop(result))


def build_parallel_orchestrator(config: AutoDevConfig, repo: Path) -> ParallelOrchestrator:
    if config.provider != "codex_cli":
        raise ProviderError("parallel development requires codex_cli with your ChatGPT login")
    integration = IntegrationManager(repo, config.parallel.git_timeout_seconds)
    budget = ApiBudgetTracker(
        config.agents.api_budget_usd, config.agents.estimated_cost_per_model_call_usd
    )

    def provider(workspace: Path) -> CodexCLIProvider:
        return CodexCLIProvider(
            config.codex_cli,
            config.agents.developer_model,
            config.agents.reviewer_model,
            workspace=workspace,
        )

    client = provider(integration.integration.path)
    return ParallelOrchestrator(
        config,
        TaskPlanner(client, config.parallel.max_tasks),
        provider,
        ReviewerAgent(client, budget),
        integration,
        SandboxChecks(config),
        budget,
    )
