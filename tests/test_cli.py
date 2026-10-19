import argparse
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from autodev.cli import _run, main
from autodev.config import AutoDevConfig
from autodev.model_policy import resolve_config
from autodev.parallel_schemas import ParallelWorkflowReport
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


@pytest.mark.parametrize("succeeded", [True, False])
def test_parallel_cli_outputs_structured_report_and_failure_exit(monkeypatch, capsys, succeeded):
    monkeypatch.setattr("autodev.cli.load_config_from_env", lambda: AutoDevConfig())
    result = ParallelWorkflowReport(
        request="two",
        run_id="test",
        started_at="now",
        integration_branch="autodev/test/integration",
        integration_worktree="worktree",
        succeeded=succeeded,
    )
    build = Mock(return_value=Mock(run_task=AsyncMock(return_value=result)))
    monkeypatch.setattr("autodev.cli.build_parallel_orchestrator", build)
    args = argparse.Namespace(
        task="two",
        task_file=None,
        example=None,
        workspace=None,
        sandbox_backend=None,
        max_iterations=None,
        parallel=True,
        repo=Path("."),
        plan_file=None,
        concurrency=2,
        max_tasks=2,
        max_corrections=3,
    )
    if succeeded:
        asyncio.run(_run(args))
    else:
        with pytest.raises(SystemExit) as error:
            asyncio.run(_run(args))
        assert error.value.code == 1
    assert '"integration_branch": "autodev/test/integration"' in capsys.readouterr().out
    assert build.call_args.args[0].parallel.max_tasks == 2


def test_parallel_settings_require_parallel_flag(monkeypatch):
    monkeypatch.setattr("autodev.cli.load_config_from_env", lambda: AutoDevConfig())
    args = argparse.Namespace(
        task="two",
        task_file=None,
        example=None,
        workspace=None,
        sandbox_backend=None,
        max_iterations=None,
        parallel=False,
        concurrency=2,
    )
    with pytest.raises(SystemExit, match="require --parallel"):
        asyncio.run(_run(args))


def test_cli_role_policy_overrides_preserve_workflow_limits(monkeypatch):
    original = AutoDevConfig()
    monkeypatch.setattr("autodev.cli.load_config_from_env", lambda: original)
    result = WorkflowResult(
        task="task",
        succeeded=False,
        attempts=[],
        workspace="workspace",
        stopped_reason="offline fixture",
        model_calls_reserved=0,
    )
    builder = Mock(return_value=Mock(run_task=AsyncMock(return_value=result)))
    monkeypatch.setattr("autodev.cli.build_orchestrator", builder)
    args = argparse.Namespace(
        task="Build modules",
        task_file=None,
        example=None,
        workspace=None,
        sandbox_backend=None,
        max_iterations=None,
        model_preset="maximum_quality",
        developer_reasoning_effort="high",
    )
    asyncio.run(_run(args))
    config = builder.call_args.args[0]
    policy = resolve_config(config)
    assert policy.architect.reasoning_effort == policy.reviewer.reasoning_effort == "xhigh"
    assert policy.developer.reasoning_effort == "high"
    assert config.parallel == original.parallel and config.codex_cli == original.codex_cli


def test_cli_parses_role_model_and_effort_flags_without_model_calls(monkeypatch):
    run = AsyncMock()
    monkeypatch.setattr("autodev.cli._run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "autodev",
            "run",
            "--task",
            "Build modules",
            "--model-preset",
            "balanced",
            "--architect-model",
            "gpt-6-astra",
            "--architect-reasoning-effort",
            "xhigh",
        ],
    )
    main()
    args = run.call_args.args[0]
    assert args.model_preset == "balanced" and args.architect_reasoning_effort == "xhigh"
