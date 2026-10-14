import argparse
import asyncio

import pytest
from pydantic import ValidationError

from autodev.cli import _run


@pytest.mark.parametrize("max_iterations", [0, -1, 4])
def test_cli_rejects_invalid_iteration_limits(max_iterations: int, monkeypatch) -> None:
    monkeypatch.setattr("autodev.cli.build_orchestrator", lambda _: pytest.fail("model reached"))
    args = argparse.Namespace(
        task="Implement add(a, b).",
        task_file=None,
        example=None,
        workspace=None,
        sandbox_backend=None,
        max_iterations=max_iterations,
    )

    with pytest.raises(ValidationError):
        asyncio.run(_run(args))
