import argparse
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from autodev.cli import _run, main
from autodev.config import AutoDevConfig
from autodev.providers import ProviderAuthenticationError
from autodev.schemas import WorkflowResult


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


def test_cli_parses_codex_provider(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr("autodev.cli._run", run)
    monkeypatch.setattr("sys.argv", ["autodev", "run", "--task", "Add", "--provider", "codex_cli"])
    main()
    assert run.call_args.args[0].provider == "codex_cli"


def test_cli_provider_overrides_environment_config(monkeypatch, capsys):
    config = AutoDevConfig(provider="openai_api")
    monkeypatch.setattr("autodev.cli.load_config_from_env", lambda: config)
    result = WorkflowResult(
        task="Add",
        succeeded=False,
        attempts=[],
        workspace="workspace",
        stopped_reason="dry run",
        model_calls_reserved=2,
    )
    build = Mock(return_value=Mock(run_task=AsyncMock(return_value=result)))
    monkeypatch.setattr("autodev.cli.build_orchestrator", build)
    args = argparse.Namespace(
        task="Add",
        task_file=None,
        example=None,
        workspace=None,
        sandbox_backend=None,
        max_iterations=2,
        provider="codex_cli",
    )
    asyncio.run(_run(args))
    actual_config = build.call_args.args[0]
    assert actual_config.provider == "codex_cli"
    assert actual_config.agents.max_iterations == 2
    assert '"succeeded": false' in capsys.readouterr().out


def test_cli_reports_provider_error_without_traceback(monkeypatch):
    monkeypatch.setattr("sys.argv", ["autodev", "run", "--task", "Add"])
    monkeypatch.setattr(
        "autodev.cli._run", AsyncMock(side_effect=ProviderAuthenticationError("Run codex login"))
    )
    with pytest.raises(SystemExit, match="Run codex login"):
        main()
