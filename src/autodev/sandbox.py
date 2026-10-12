from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol, Sequence

from autodev.schemas import TestRunResult


class SandboxBackend(Protocol):
    def run_pytest(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> TestRunResult:
        """Run the fixed pytest command or report that execution is disabled."""
        raise NotImplementedError


def _trim_output(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return f"{value[:max_chars]}\n... truncated {omitted} characters ..."


class DryRunSandbox:
    def run_pytest(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> TestRunResult:
        _ = workspace, timeout_seconds, max_output_chars
        return TestRunResult(
            command=list(command),
            exit_code=None,
            skipped=True,
            reason="dry-run mode: generated code execution is disabled",
        )


class DockerSandbox:
    def __init__(self, image: str) -> None:
        self.image = image

    def run_pytest(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> TestRunResult:
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "256m",
            "--pids-limit",
            "128",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={workspace.resolve()},dst=/workspace",
            "-w",
            "/workspace",
            self.image,
            *command,
        ]
        try:
            completed = subprocess.run(
                docker_command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except FileNotFoundError:
            return TestRunResult(
                command=list(command),
                exit_code=None,
                skipped=True,
                reason="Docker executable was not found; execution disabled",
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return TestRunResult(
                command=list(command),
                exit_code=None,
                stdout=_trim_output(stdout, max_output_chars),
                stderr=_trim_output(stderr, max_output_chars),
                timed_out=True,
                reason=f"pytest timed out after {timeout_seconds} seconds",
            )

        return TestRunResult(
            command=list(command),
            exit_code=completed.returncode,
            stdout=_trim_output(completed.stdout, max_output_chars),
            stderr=_trim_output(completed.stderr, max_output_chars),
        )
