"""Multi-stage orchestration over the existing developer, Git and Docker boundaries."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

from autodev.agents import ReviewerAgent
from autodev.architect import ProjectArchitect
from autodev.budget import BudgetExceededError
from autodev.checkpoints import CheckpointStore, RecoveryRequired, configuration_digest
from autodev.integration import (
    GitOperationError,
    IntegrationConflict,
    IntegrationManager,
    TaskWorktree,
)
from autodev.parallel import ParallelOrchestrator, build_parallel_orchestrator, timestamp
from autodev.parallel_schemas import AgentAttempt
from autodev.planning import responsible_tasks
from autodev.project_models import (
    CheckpointEntry,
    DependencyEngine,
    MilestoneState,
    ProjectReport,
    ProjectRound,
    ProjectTaskResult,
    project_path,
)
from autodev.providers import ProviderError
from autodev.schemas import GeneratedFile
from autodev.web.security import contained
from autodev.workspace import WorkspaceViolation


class ProjectOrchestrator(ParallelOrchestrator):
    def __init__(self, *args, architect: ProjectArchitect, **kwargs):
        super().__init__(*args, **kwargs)
        self.architect = architect
        self.pause_requested = False
        self.store = CheckpointStore(self.integration)
        self.session_start = None
        self.prior_duration = 0

    def write_report(self):
        if self.integration.created and self.current_report:
            if self.session_start is not None:
                self.current_report.duration_seconds = (
                    self.prior_duration + monotonic() - self.session_start
                )
            self.current_report.model_calls_reserved = self.calls
            relative = f".autodev/runs/{self.integration.run_id}/project_report"
            path = contained(self.integration.repo, relative + ".json")
            temporary = contained(self.integration.repo, relative + ".tmp")
            temporary.write_text(self.current_report.model_dump_json(indent=2), encoding="utf-8")
            temporary.replace(path)

    def notify(self, stage, **details):
        self.write_report()
        super().notify(stage, **details)

    def request_pause(self):
        if self.current_report and self.current_report.reviewer_execution:
            raise RuntimeError("Final review has started; pause is no longer available")
        self.pause_requested = True
        self.notify("pause_requested")

    async def snapshot(self):
        files, total = [], 0
        tree = self.integration.integration.path
        paths = (await self.integration.git(tree, "ls-files", "-z")).split("\0")
        for path in sorted(filter(None, paths)):
            if Path(path).suffix not in {".py", ".md", ".json", ".txt", ".html", ".css", ".toml"}:
                continue
            try:
                project_path(path, writable=False)
            except ValueError:
                continue
            file = contained(tree, path)
            if file.stat().st_size > 256_000:
                continue
            content = file.read_text(encoding="utf-8")[:8000]
            total += len(content)
            if len(files) >= 200 or total > 128_000:
                raise ValueError("Repository context exceeds Phase 1 planning limits")
            files.append(GeneratedFile(path=path, content=content))
        return files

    async def run_task(self, request, seed_tests_dir=None, plan=None, *, resume=None):
        if seed_tests_dir is not None or plan is not None:
            raise ValueError("Project runs use existing trusted tests and the Project Architect")
        self.pause_requested = False
        start = monotonic()
        report = ProjectReport(
            request=request,
            run_id=self.integration.run_id,
            started_at=timestamp(),
            integration_branch=self.integration.integration.branch,
            integration_worktree=str(self.integration.integration.path),
            configuration_digest=configuration_digest(self.config),
            workflow_limits=self.config.parallel.model_dump(),
        )
        # Do not replace a retained report when recovery verification fails.
        if resume is not None:
            with self.store.lock():
                report = await self.store.restore(resume, self.config)
                self.calls = report.model_calls_reserved
                self.budget.calls_reserved = self.calls
                return await self.drive(report, start)
        self.current_report = report
        try:
            await asyncio.wait_for(
                self.integration.prepare(), self.config.parallel.git_timeout_seconds * 3
            )
        except Exception:
            report.integration_status = "failed"
            report.stopped_reason = "Repository preparation failed; source checkout was preserved"
            report.finished_at = timestamp()
            self.notify("finished")
            return report
        with self.store.lock():
            return await self.drive(report, start)

    async def drive(self, report, start):
        self.current_report = report
        self.session_start, self.prior_duration = start, report.duration_seconds
        report.finished_at, report.succeeded = "", False
        try:
            remaining = (
                self.config.parallel.workflow_timeout_seconds
                - self.prior_duration
                - (monotonic() - start)
            )
            if remaining <= 0:
                raise TimeoutError
            await asyncio.wait_for(self.execute_project(report), remaining)
        except asyncio.CancelledError:
            report.integration_status, report.checkpoint_safe = "cancelled", False
            report.stopped_reason = (
                "Cancelled; worktrees retained. Mid-stage force-resume is disabled."
            )
            raise
        except TimeoutError:
            report.integration_status, report.checkpoint_safe = "timed_out", False
            report.stopped_reason = "Project workflow deadline exceeded"
        except IntegrationConflict as error:
            report.integration_status, report.checkpoint_safe = "conflict", False
            report.conflicts, report.stopped_reason = error.paths, str(error)
        except (ProviderError, BudgetExceededError, GitOperationError, WorkspaceViolation) as error:
            report.integration_status, report.checkpoint_safe = "failed", False
            report.stopped_reason = str(error)
        except Exception:
            report.integration_status, report.checkpoint_safe = "failed", False
            report.stopped_reason = (
                "Project stopped safely; inspect plan, limits and retained worktrees"
            )
        finally:
            report.finished_at = timestamp()
            if report.integration_status not in {"paused", "reviewed"}:
                for milestone in report.milestones:
                    if milestone.status == "running":
                        milestone.status = (
                            "interrupted" if report.integration_status == "cancelled" else "failed"
                        )
                        milestone.finished_at = timestamp()
            report.duration_seconds = self.prior_duration + monotonic() - start
            report.report_path = str(self.integration.root / "project_report.json")
            self.notify("finished")
        return report

    async def boundary(self, report, label):
        report.duration_seconds = self.prior_duration + monotonic() - self.session_start
        report.checkpoint_safe = True
        report.integration_status = "paused" if self.pause_requested else "integrated"
        report.checkpoint_history.append(
            CheckpointEntry(
                number=len(report.checkpoint_history) + 1,
                at=timestamp(),
                label=label,
                commit=report.integration_commit,
            )
        )
        report.model_calls_reserved = self.calls
        try:
            await self.store.save(report)
        except BaseException:
            report.checkpoint_history.pop()
            report.checkpoint_safe = False
            raise
        if self.pause_requested:
            report.integration_status = "paused"
        self.notify("paused" if self.pause_requested else "checkpoint_saved")
        return self.pause_requested

    async def execute_project(self, report):
        manager = self.integration
        if report.specification is None:
            report.source_branch, report.base_commit = manager.source_branch, manager.base_commit
            report.integration_commit = manager.base_commit
            self.reserve_call()
            self.budget.reserve_call("project architecture")
            report.planner_execution = AgentAttempt(
                number=1, agent_id="architect", started_at=timestamp()
            )
            planning_start = monotonic()
            self.notify("architecting")
            try:
                report.specification = await asyncio.wait_for(
                    self.architect.design(report.request, await self.snapshot()),
                    self.config.parallel.agent_timeout_seconds,
                )
            except BaseException:
                report.planner_execution.error = "Architecture failed validation or was interrupted"
                raise
            finally:
                report.planner_execution.finished_at = timestamp()
                report.planner_execution.duration_seconds = monotonic() - planning_start
            report.milestones = [MilestoneState(id=m.id) for m in report.specification.milestones]
            if await self.boundary(report, "architecture_validated"):
                return
        engine = DependencyEngine(report.specification)
        for milestone, state in zip(
            report.specification.milestones, report.milestones, strict=True
        ):
            if state.status == "completed":
                continue
            report.active_milestone, state.status = milestone.id, "running"
            state.started_at = state.started_at or timestamp()
            while not set(milestone.task_ids) <= set(report.validated_tasks):
                ready = engine.ready(
                    milestone, set(report.validated_tasks), self.config.parallel.concurrency
                )
                if not ready:
                    raise ValueError("No schedulable dependency tasks")
                report.checkpoint_safe = False
                self.notify("scheduling", task_ids=[t.id for t in ready])
                selected = []
                for task in ready:
                    tree = await manager.create_task(task, report.integration_commit)
                    result = ProjectTaskResult(
                        task=task,
                        branch=tree.branch,
                        worktree=str(tree.path),
                        base_commit=report.integration_commit,
                    )
                    report.tasks.append(result)
                    selected.append(result)
                test_paths = {
                    p
                    for task in report.specification.tasks
                    if task.id in report.validated_tasks or task in ready
                    for p in task.test_paths
                }
                if set(milestone.task_ids) <= set(report.validated_tasks) | {t.id for t in ready}:
                    for previous in report.specification.milestones:
                        test_paths.update(previous.test_paths)
                        if previous.id == milestone.id:
                            break
                if not await self.develop_batch(report, selected, sorted(test_paths)):
                    state.status = "failed"
                    return
                for result in selected:
                    result.status = "validated"
                    report.validated_tasks.append(result.task.id)
                if await self.boundary(
                    report, f"tasks_validated:{','.join(t.task.id for t in selected)}"
                ):
                    return
            state.status, state.finished_at, state.commit = (
                "completed",
                timestamp(),
                report.integration_commit,
            )
            if await self.boundary(report, "milestone_completed:" + milestone.id):
                return
        report.checkpoint_safe = False
        self.notify("validating_project")
        final = ProjectRound(number=len(report.rounds), milestone_id="final")
        report.rounds.append(final)
        final.checks = await self.checks.run(manager.integration.path)
        self.notify("checks_finished")
        if not final.checks.passed:
            report.integration_status = (
                "infrastructure_failed" if final.checks.infrastructure_failed else "checks_failed"
            )
            report.stopped_reason = (
                "Final full-suite validation failed; no later milestones will run"
            )
            return
        if await self.boundary(report, "project_validation_passed"):
            return
        report.checkpoint_safe = False
        self.reserve_call()
        report.reviewer_execution = AgentAttempt(
            number=1, agent_id="reviewer", started_at=timestamp()
        )
        review_start = monotonic()
        self.notify("reviewing")
        try:
            report.review = await asyncio.wait_for(
                self.reviewer.review(
                    report.request + "\n" + report.specification.model_dump_json(),
                    await self.snapshot(),
                    final.checks.pytest,
                ),
                self.config.parallel.agent_timeout_seconds,
            )
        except BaseException:
            report.reviewer_execution.error = "Review failed or was interrupted"
            raise
        finally:
            report.reviewer_execution.finished_at = timestamp()
            report.reviewer_execution.duration_seconds = monotonic() - review_start
        await self.store.verify_tree(
            manager.repo, report.base_commit, report.source_branch, source=True
        )
        await self.store.verify_tree(
            manager.integration.path, report.integration_commit, report.integration_branch
        )
        report.succeeded = report.review.approved
        report.integration_status = "reviewed" if report.succeeded else "review_rejected"
        report.stopped_reason = (
            "Project validated and reviewed" if report.succeeded else "Project review rejected"
        )

    async def develop_batch(self, report, selected, test_paths):
        context, feedback = await self.snapshot(), None
        pending = list(selected)
        request = (
            report.request + "\nArchitecture contracts:\n" + report.specification.model_dump_json()
        )
        for correction in range(self.config.parallel.max_corrections + 1):
            await self._develop(pending, request, context, feedback)
            if any(t.status != "completed" for t in pending):
                report.integration_status, report.stopped_reason = (
                    "agent_failed",
                    "A project developer failed",
                )
                return False
            current = ProjectRound(
                number=len(report.rounds),
                milestone_id=report.active_milestone,
                test_paths=test_paths,
                correction_attempt=correction,
            )
            report.rounds.append(current)
            for result in pending:
                self.notify("integrating", task_id=result.task.id)
                commit = result.attempts[-1].commit
                if commit:
                    report.integration_commit = await self.integration.integrate(commit)
                    current.commits.append(report.integration_commit)
            self.notify("validating")
            current.checks = await self.checks.run(self.integration.integration.path, test_paths)
            self.notify("checks_finished")
            if current.checks.infrastructure_failed or current.checks.unavailable:
                report.integration_status = "infrastructure_failed"
                report.stopped_reason = (
                    "Validation environment unavailable; no developer correction requested"
                )
                return False
            if current.checks.passed:
                return True
            feedback = current.checks.failure_output()
            owners = responsible_tasks(SimpleNamespace(tasks=[t.task for t in selected]), feedback)
            current.correction_tasks = sorted(owners)
            pending = [t for t in selected if t.task.id in owners]
            context = await self.snapshot()
            if correction < self.config.parallel.max_corrections:
                self.notify("correcting", task_ids=sorted(owners))
        report.integration_status, report.stopped_reason = (
            "checks_failed",
            "Project correction limit reached",
        )
        return False


def build_project_orchestrator(config, repo, run_id=None):
    base = build_parallel_orchestrator(config, repo)
    if run_id is not None:
        if not re.fullmatch(r"[0-9a-f]{12}", run_id):
            raise RecoveryRequired("Invalid project run ID")
        manager = IntegrationManager(repo, config.parallel.git_timeout_seconds)
        manager.run_id, manager.root = run_id, repo.resolve() / ".autodev/runs" / run_id
        manager.integration = TaskWorktree(
            manager.root / "integration", f"autodev/{run_id}/integration"
        )
        base.integration = manager
    client = base.developer_factory(base.integration.integration.path)
    base.reviewer = ReviewerAgent(client, base.budget)
    return ProjectOrchestrator(
        config,
        base.planner,
        base.developer_factory,
        base.reviewer,
        base.integration,
        base.checks,
        base.budget,
        architect=ProjectArchitect(client, config.parallel.max_tasks),
    )
