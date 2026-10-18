from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from autodev.planning import DevelopmentTask
from autodev.providers import ProviderError, _codex_environment, _exchange
from autodev.schemas import CodeGenerationResult
from autodev.workspace import Workspace, WorkspaceViolation


class GitOperationError(RuntimeError):
    """A fixed Git operation failed; the caller's checkout is never reset or cleaned."""


class IntegrationConflict(GitOperationError):
    def __init__(self, paths: list[str]) -> None:
        super().__init__("integration conflict; disposable integration worktree retained")
        self.paths = paths


@dataclass(frozen=True)
class TaskWorktree:
    path: Path
    branch: str


class IntegrationManager:
    """Own disposable branches/worktrees; never checkout/merge/reset the source checkout."""

    def __init__(self, repo: Path, timeout_seconds: int = 30) -> None:
        self.repo = repo.resolve()
        self.run_id = uuid4().hex[:12]
        self.root = self.repo / ".autodev" / "runs" / self.run_id
        self.integration = TaskWorktree(
            self.root / "integration", f"autodev/{self.run_id}/integration"
        )
        self.timeout_seconds = timeout_seconds
        self.base_commit = ""
        self.source_branch = ""
        self.tasks: dict[str, TaskWorktree] = {}
        self.created = False

    async def git(self, cwd: Path, *arguments: str) -> str:
        env = _codex_environment() | {
            "GIT_TERMINAL_PROMPT": "0",
        }
        command = [
            "git",
            "-c",
            f"safe.directory={cwd.resolve().as_posix()}",
            "-c",
            f"core.hooksPath={(self.root / 'hooks').as_posix()}",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=AutoDev",
            "-c",
            "user.email=autodev@localhost",
            *arguments,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            raise GitOperationError(
                "Git could not start; check installation and permissions"
            ) from None
        try:
            stdout, _ = await asyncio.wait_for(
                _exchange(process, b"", 2_000_000), self.timeout_seconds
            )
        except (TimeoutError, OSError, ProviderError):
            raise GitOperationError(
                "Git operation timed out or failed during communication"
            ) from None
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.communicate()
        if process.returncode:
            raise GitOperationError(f"Git {arguments[0]} failed (exit {process.returncode})")
        return stdout.decode("utf-8", errors="strict").rstrip("\n")

    async def prepare(self) -> None:
        top = Path(await self.git(self.repo, "rev-parse", "--show-toplevel")).resolve()
        if top != self.repo:
            raise GitOperationError("--repo must name the repository root")
        self.base_commit = await self.git(self.repo, "rev-parse", "HEAD")
        self.source_branch = await self.git(self.repo, "branch", "--show-current")
        await self.validate_tree(self.repo)
        if await self.git(self.repo, "status", "--porcelain", "--untracked-files=no"):
            raise GitOperationError(
                "commit or stash tracked changes yourself before parallel execution"
            )
        if self.root.resolve().is_relative_to(self.repo) is False:
            raise GitOperationError("worktree storage must stay inside the repository")
        self.root.mkdir(parents=True, exist_ok=False)
        self.created = True
        (self.root / "hooks").mkdir()
        await self._add(self.integration)

    async def validate_tree(self, cwd: Path) -> None:
        entries = (await self.git(cwd, "ls-files", "--stage", "-z")).split("\0")
        tracked_paths = []
        for entry in filter(None, entries):
            metadata, name = entry.split("\t", 1)
            tracked_paths.append(name)
            parts = name.casefold().split("/")
            if metadata.startswith(("120000", "160000")):
                raise GitOperationError("parallel baseline cannot contain symlinks or submodules")
            if any(
                part in {".aws", ".codex", "auth.json"}
                or (part.startswith(".env") and part != ".env.example")
                for part in parts
            ):
                raise GitOperationError("parallel baseline contains a protected credential path")
        await self._assert_safe_attributes(cwd, tracked_paths)

    async def _add(self, worktree: TaskWorktree, start_commit: str | None = None) -> None:
        worktree.path.parent.mkdir(parents=True, exist_ok=True)
        await self.git(
            self.repo,
            "worktree",
            "add",
            "-b",
            worktree.branch,
            str(worktree.path),
            start_commit or self.base_commit,
        )

    async def _assert_safe_attributes(self, cwd: Path, paths: list[str]) -> None:
        attributes = await self.git(cwd, "check-attr", "filter", "merge", "--", *paths)
        for line in attributes.splitlines():
            _, attribute, value = line.rsplit(": ", 2)
            allowed = {"unspecified", "unset"}
            if attribute == "merge":
                allowed |= {"set", "text", "binary"}
            if value not in allowed:
                raise GitOperationError(
                    "Git filters or custom merge drivers require explicit review; execution refused"
                )

    async def create_task(
        self, task: DevelopmentTask, start_commit: str | None = None
    ) -> TaskWorktree:
        if task.id in self.tasks:
            raise GitOperationError("task worktree already exists")
        worktree = TaskWorktree(
            self.root / "tasks" / task.id, f"autodev/{self.run_id}/task-{task.id}"
        )
        if start_commit is not None and (
            len(start_commit) not in (40, 64)
            or any(c not in "0123456789abcdef" for c in start_commit)
        ):
            raise GitOperationError("invalid task base commit")
        await self._add(worktree, start_commit)
        self.tasks[task.id] = worktree
        return worktree

    async def seed_tests(self, source: Path) -> str:
        paths = []
        workspace = Workspace(self.integration.path)
        for file in source.rglob("*"):
            if file.is_symlink():
                raise WorkspaceViolation("seed tests cannot contain symlinks")
            if file.is_file():
                relative = "tests/" + file.relative_to(source).as_posix()
                if file.suffix != ".py" or workspace.resolve(relative).exists():
                    raise WorkspaceViolation("seed tests must be new Python test files")
                paths.append(relative)
        if not paths:
            raise WorkspaceViolation("no seed tests were provided")
        await self._assert_safe_attributes(self.integration.path, paths)
        workspace.copy_tree_into(source, "tests")
        await self.git(self.integration.path, "--literal-pathspecs", "add", "--", *paths)
        await self.git(
            self.integration.path, "commit", "-m", "AutoDev: seed fixed acceptance tests"
        )
        return await self.git(self.integration.path, "rev-parse", "HEAD")

    def apply(self, task: DevelopmentTask, generated: CodeGenerationResult) -> None:
        from autodev.project_models import ProjectTask, project_path

        if isinstance(task, ProjectTask):
            for file in generated.files:
                project_path(file.path)
                if len(file.content.encode("utf-8")) > 256_000:
                    raise WorkspaceViolation("Project file exceeds its bounded output size")
                if file.path.endswith(".json"):
                    json.loads(file.content)
        paths = [file.path for file in generated.files]
        if len(paths) != len(set(paths)) or set(paths) != set(task.owned_files):
            raise WorkspaceViolation(
                "agent must return every owned file exactly once and no other files"
            )
        workspace = Workspace(self.tasks[task.id].path)
        workspace.write_generated_files(
            generated.files,
            protected_prefixes=("tests", ".git"),
            allowed_paths=tuple(task.owned_files),
        )

    async def commit_task(self, task: DevelopmentTask, attempt: int) -> str | None:
        worktree = self.tasks[task.id]
        await self._assert_safe_attributes(worktree.path, task.owned_files)
        changed = await self.git(
            worktree.path, "diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z"
        )
        untracked = await self.git(
            worktree.path, "ls-files", "--others", "--exclude-standard", "-z"
        )
        found = set(filter(None, (changed + "\0" + untracked).split("\0")))
        if not found.issubset(set(task.owned_files)):
            raise WorkspaceViolation("worktree contains changes outside assigned scope")
        # Explicit paths only: never `git add .`, never a model-supplied command.
        await self.git(worktree.path, "--literal-pathspecs", "add", "--", *task.owned_files)
        staged = set(
            filter(
                None,
                (
                    await self.git(
                        worktree.path,
                        "diff",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--cached",
                        "--name-only",
                        "-z",
                    )
                ).split("\0"),
            )
        )
        if not staged.issubset(set(task.owned_files)):
            raise WorkspaceViolation("staged changes are outside assigned scope")
        if not staged:
            return None
        await self.git(worktree.path, "commit", "-m", f"AutoDev {task.id}: attempt {attempt}")
        return await self.git(worktree.path, "rev-parse", "HEAD")

    async def integrate(self, commit: str) -> str:
        # Only locally produced full object IDs, never branch names from model output.
        if len(commit) not in (40, 64) or any(ch not in "0123456789abcdef" for ch in commit):
            raise GitOperationError("invalid integration commit ID")
        try:
            await self.git(self.integration.path, "cherry-pick", commit)
        except GitOperationError:
            conflicts = await self.git(
                self.integration.path,
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--name-only",
                "--diff-filter=U",
            )
            if conflicts:
                raise IntegrationConflict(conflicts.splitlines()) from None
            raise
        return await self.git(self.integration.path, "rev-parse", "HEAD")
