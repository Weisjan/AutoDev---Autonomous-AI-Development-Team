"""Immutable boundary snapshots and conservative Git recovery verification."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from autodev.config import AutoDevConfig
from autodev.integration import GitOperationError, IntegrationManager, TaskWorktree
from autodev.project_models import ProjectReport
from autodev.web.security import contained


class RecoveryRequired(GitOperationError):
    """No automatic recovery is authorized when a boundary cannot be verified."""


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def configuration_digest(config: AutoDevConfig) -> str:
    return digest(config.model_dump(mode="json"))


class Checkpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = 1
    report: ProjectReport
    task_heads: dict[str, str]
    checksum: str = ""

    def seal(self):
        self.report = ProjectReport.model_validate_json(self.report.model_dump_json())
        self.checksum = digest(self.model_dump(mode="json", exclude={"checksum"}))
        return self

    def verify(self):
        if self.version != 1 or self.checksum != digest(
            self.model_dump(mode="json", exclude={"checksum"})
        ):
            raise RecoveryRequired(
                "Checkpoint checksum/version mismatch; explicit manual review required"
            )


class CheckpointStore:
    def __init__(self, integration: IntegrationManager):
        self.integration = integration

    @contextmanager
    def lock(self):
        path = contained(
            self.integration.repo, f".autodev/runs/{self.integration.run_id}/project.lock"
        )
        with path.open("a+b") as handle:
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RecoveryRequired("Project is active in another process") from None
            try:
                yield
            finally:
                handle.seek(0)
                if sys.platform == "win32":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    async def save(self, report: ProjectReport):
        manager = self.integration
        await self.verify_tree(manager.repo, report.base_commit, report.source_branch, source=True)
        await self.verify_tree(
            manager.integration.path, report.integration_commit, report.integration_branch
        )
        heads = {
            task.task.id: await manager.git(Path(task.worktree), "rev-parse", "HEAD")
            for task in report.tasks
        }
        for task in report.tasks:
            expected = next(
                (a.commit for a in reversed(task.attempts) if a.commit), task.base_commit
            )
            if heads[task.task.id] != expected or await manager.git(
                Path(task.worktree), "status", "--porcelain", "--untracked-files=all"
            ):
                raise RecoveryRequired(
                    "Task worktree changed before checkpoint; manual review required"
                )
        snapshot = report.model_copy(deep=True)
        snapshot.checkpoint_digest = ""
        checkpoint = Checkpoint(report=snapshot, task_heads=heads).seal()
        number = report.checkpoint_history[-1].number
        path = contained(
            manager.repo, f".autodev/runs/{manager.run_id}/checkpoints/{number:03d}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        # Never overwrite a previous checkpoint, even after a crash between these writes.
        with path.open("x", encoding="utf-8") as handle:
            handle.write(checkpoint.model_dump_json(indent=2))
        report.checkpoint_digest = checkpoint.checksum

    def load(self, number: int) -> Checkpoint:
        if not 1 <= number <= 100:
            raise RecoveryRequired("Invalid checkpoint number; explicit manual review required")
        path = contained(
            self.integration.repo,
            f".autodev/runs/{self.integration.run_id}/checkpoints/{number:03d}.json",
        )
        if path.stat().st_size > 2_000_000:
            raise RecoveryRequired("Oversized checkpoint")
        checkpoint = Checkpoint.model_validate_json(path.read_bytes())
        checkpoint.verify()
        return checkpoint

    async def restore(self, live: ProjectReport, config: AutoDevConfig) -> ProjectReport:
        try:
            if (
                not live.checkpoint_safe
                or not live.checkpoint_history
                or live.succeeded
                or live.integration_status == "cancelled"
            ):
                raise RecoveryRequired(
                    "No verified resumable boundary; explicit manual review required"
                )
            checkpoint = self.load(live.checkpoint_history[-1].number)
            report = checkpoint.report
            if (
                live.checkpoint_digest != checkpoint.checksum
                or report.run_id != self.integration.run_id
                or report.configuration_digest != configuration_digest(config)
                or live.integration_commit != report.integration_commit
                or live.validated_tasks != report.validated_tasks
            ):
                raise RecoveryRequired(
                    "Checkpoint identity/configuration changed; manual review required"
                )
            manager = self.integration
            expected_branch = f"autodev/{manager.run_id}/integration"
            if (
                report.integration_branch != expected_branch
                or Path(report.integration_worktree).resolve() != manager.integration.path.resolve()
                or not report.specification
                or set(report.validated_tasks) != {t.task.id for t in report.tasks}
                or any(t.status != "validated" for t in report.tasks)
                or set(checkpoint.task_heads) != set(report.validated_tasks)
            ):
                raise RecoveryRequired("Inconsistent checkpoint task state; manual review required")
            specifications = {t.id: t for t in report.specification.tasks}
            if (
                any(
                    t.task.id not in specifications
                    or t.task != specifications[t.task.id]
                    or not set(t.task.depends_on) <= set(report.validated_tasks)
                    for t in report.tasks
                )
                or [m.id for m in report.milestones]
                != [m.id for m in report.specification.milestones]
                or any(
                    m.status == "completed" and not set(s.task_ids) <= set(report.validated_tasks)
                    for m, s in zip(report.milestones, report.specification.milestones, strict=True)
                )
            ):
                raise RecoveryRequired("Checkpoint dependency/milestone state is inconsistent")
            manager.base_commit, manager.source_branch = report.base_commit, report.source_branch
            await self.verify_tree(
                manager.repo, report.base_commit, report.source_branch, source=True
            )
            await self.verify_tree(
                manager.integration.path, report.integration_commit, expected_branch
            )
            for task in report.tasks:
                expected = TaskWorktree(
                    manager.root / "tasks" / task.task.id,
                    f"autodev/{manager.run_id}/task-{task.task.id}",
                )
                if (
                    Path(task.worktree).resolve() != expected.path.resolve()
                    or task.branch != expected.branch
                ):
                    raise RecoveryRequired("Checkpoint worktree paths changed")
                await self.verify_tree(
                    expected.path, checkpoint.task_heads[task.task.id], expected.branch
                )
                manager.tasks[task.task.id] = expected
            manager.created = True
            report.checkpoint_digest = checkpoint.checksum
            if live.duration_seconds < report.duration_seconds:
                raise RecoveryRequired("Checkpoint execution time regressed")
            report.duration_seconds = live.duration_seconds
            return report
        except RecoveryRequired:
            raise
        except (OSError, ValueError, KeyError, GitOperationError):
            raise RecoveryRequired(
                "Cannot verify repository/checkpoint state. Inspect retained worktrees and "
                "explicitly confirm a new run after manual recovery; force-resume is disabled."
            ) from None

    async def verify_tree(self, path, commit, branch, source=False):
        manager = self.integration
        if not commit or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            raise RecoveryRequired("Invalid checkpoint commit")
        contained(manager.repo, path.relative_to(manager.repo).as_posix())
        common = Path(await manager.git(path, "rev-parse", "--git-common-dir"))
        source_common = Path(await manager.git(manager.repo, "rev-parse", "--git-common-dir"))
        if (common if common.is_absolute() else path / common).resolve() != (
            source_common if source_common.is_absolute() else manager.repo / source_common
        ).resolve():
            raise RecoveryRequired("Worktree belongs to a different repository")
        if (
            Path(await manager.git(path, "rev-parse", "--show-toplevel")).resolve()
            != path.resolve()
        ):
            raise RecoveryRequired("Worktree identity changed")
        await manager.validate_tree(path)
        if (
            await manager.git(path, "rev-parse", "HEAD") != commit
            or await manager.git(path, "branch", "--show-current") != branch
            or await manager.git(
                path,
                "status",
                "--porcelain",
                "--untracked-files=no" if source else "--untracked-files=all",
            )
        ):
            raise RecoveryRequired(
                "Commit, branch or uncommitted work changed; manual review required"
            )
        for state in (
            "CHERRY_PICK_HEAD",
            "MERGE_HEAD",
            "REVERT_HEAD",
            "rebase-merge",
            "rebase-apply",
        ):
            marker = Path(await manager.git(path, "rev-parse", "--git-path", state))
            if (marker if marker.is_absolute() else path / marker).exists():
                raise RecoveryRequired("Unfinished Git operation; explicit manual review required")
