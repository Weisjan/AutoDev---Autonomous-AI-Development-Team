from __future__ import annotations

import subprocess
from collections.abc import Sequence
from csv import writer
from io import StringIO
from pathlib import Path
from threading import Thread
from typing import BinaryIO, Protocol
from uuid import uuid4

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


def _run_bounded(
    command: Sequence[str], timeout_seconds: int, max_output_chars: int
) -> tuple[subprocess.CompletedProcess[str], bool]:
    # Drain both pipes while retaining only a bounded prefix of untrusted output.
    outputs = [bytearray(), bytearray()]
    truncated = [False, False]

    def drain(stream: BinaryIO, index: int) -> None:
        while chunk := stream.read(4096):
            remaining = max_output_chars - len(outputs[index])
            outputs[index].extend(chunk[:remaining])
            truncated[index] |= len(chunk) > remaining

    timed_out = False
    with subprocess.Popen(
        list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    ) as process:
        assert process.stdout is not None and process.stderr is not None
        readers = [
            Thread(target=drain, args=(process.stdout, 0), daemon=True),
            Thread(target=drain, args=(process.stderr, 1), daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            for reader in readers:
                reader.join()

    text_outputs = [
        data.decode("utf-8", errors="replace") + ("\n... output truncated ..." if cut else "")
        for data, cut in zip(outputs, truncated, strict=True)
    ]
    return subprocess.CompletedProcess(list(command), process.returncode, *text_outputs), timed_out


def _workspace_mount(workspace: Path) -> str:
    mount = StringIO()
    writer(mount, lineterminator="").writerow(
        ["type=bind", f"src={workspace.resolve()}", "dst=/workspace", "readonly"]
    )
    return mount.getvalue()


class DryRunSandbox:
    def run_ruff(
        self, workspace: Path, timeout_seconds: int, max_output_chars: int
    ) -> TestRunResult:
        return self.run_pytest(workspace, DEFAULT_RUFF_COMMAND, timeout_seconds, max_output_chars)

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
        return self._run_command(workspace, command, timeout_seconds, max_output_chars)

    def run_ruff(
        self, workspace: Path, timeout_seconds: int, max_output_chars: int
    ) -> TestRunResult:
        return self._run_command(workspace, DEFAULT_RUFF_COMMAND, timeout_seconds, max_output_chars)

    def _run_command(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> TestRunResult:
        container_name = f"autodev-{uuid4().hex}"
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--name",
            container_name,
            "--pull",
            "never",
            "--user",
            "65534:65534",
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "256m",
            "--memory-swap",
            "256m",
            "--pids-limit",
            "128",
            "--read-only",
            "--log-driver",
            "none",
            "--ulimit",
            "nofile=256:256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "PYTEST_ADDOPTS=-p no:cacheprovider",
            "--env",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            "--mount",
            _workspace_mount(workspace),
            "-w",
            "/workspace",
            self.image,
            *command,
        ]
        started = True
        result = None
        try:
            completed, timed_out = _run_bounded(docker_command, timeout_seconds, max_output_chars)
            infrastructure_failure = completed.returncode in (125, 126, 127) and not timed_out
            result = TestRunResult(
                command=list(command),
                exit_code=None if timed_out else completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                timed_out=timed_out,
                skipped=infrastructure_failure,
                reason=(
                    f"pytest timed out after {timeout_seconds} seconds"
                    if timed_out
                    else "Docker could not start the test command; execution disabled"
                    if infrastructure_failure
                    else None
                ),
            )
        except OSError as exc:
            started = False
            result = TestRunResult(
                command=list(command),
                exit_code=None,
                skipped=True,
                reason=f"Docker CLI unavailable; execution disabled: {exc}",
            )
        finally:
            if started:
                cleanup_error = self._remove_container(container_name, max_output_chars)
                if cleanup_error and result is not None:
                    result.skipped = True
                    result.reason = f"{result.reason or 'test run finished'}; {cleanup_error}"

        return result

    @staticmethod
    def _remove_container(container_name: str, max_output_chars: int) -> str | None:
        try:
            completed, timed_out = _run_bounded(
                ["docker", "rm", "--force", container_name], 10, max_output_chars
            )
        except OSError as exc:
            return f"container cleanup failed: {exc}"
        if timed_out:
            return "container cleanup timed out; verify Docker containers manually"
        if completed.returncode != 0 and "no such container" not in completed.stderr.lower():
            return f"container cleanup failed: {completed.stderr}"
        return None


DEFAULT_RUFF_COMMAND = [
    "python",
    "-m",
    "ruff",
    "check",
    ".",
    "--isolated",
    "--no-cache",
    "--select",
    "E,F,I,UP,B,SIM",
    "--target-version",
    "py311",
    "--line-length",
    "100",
    "--output-format",
    "concise",
]
