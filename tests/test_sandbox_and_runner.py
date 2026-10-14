from collections.abc import Sequence
from pathlib import Path

from autodev.runner import DEFAULT_PYTEST_COMMAND
from autodev.runner import TestRunner as PytestRunner
from autodev.sandbox import DryRunSandbox
from autodev.schemas import TestRunResult as RunResult


class RecordingSandbox:
    def __init__(self) -> None:
        self.command: list[str] | None = None

    def run_pytest(
        self,
        workspace: Path,
        command: Sequence[str],
        timeout_seconds: int,
        max_output_chars: int,
    ) -> RunResult:
        self.command = list(command)
        return RunResult(command=list(command), exit_code=0)


def test_dry_run_sandbox_skips_execution(tmp_path: Path) -> None:
    result = DryRunSandbox().run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 1, 100)

    assert result.skipped
    assert not result.passed
    assert "dry-run" in (result.reason or "")


def test_runner_uses_fixed_pytest_command(tmp_path: Path) -> None:
    sandbox = RecordingSandbox()
    runner = PytestRunner(sandbox=sandbox)

    result = runner.run(tmp_path)

    assert result.passed
    assert sandbox.command == DEFAULT_PYTEST_COMMAND
