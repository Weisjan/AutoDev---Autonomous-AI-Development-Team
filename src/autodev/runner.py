from __future__ import annotations

from pathlib import Path

from autodev.sandbox import SandboxBackend
from autodev.schemas import TestRunResult

DEFAULT_PYTEST_COMMAND = ["python", "-m", "pytest", "tests", "--tb=short", "-q"]


class TestRunner:
    def __init__(
        self,
        sandbox: SandboxBackend,
        timeout_seconds: int = 30,
        max_output_chars: int = 20_000,
    ) -> None:
        self._sandbox = sandbox
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    def run(self, workspace: Path) -> TestRunResult:
        return self._sandbox.run_pytest(
            workspace=workspace,
            command=DEFAULT_PYTEST_COMMAND,
            timeout_seconds=self._timeout_seconds,
            max_output_chars=self._max_output_chars,
        )
