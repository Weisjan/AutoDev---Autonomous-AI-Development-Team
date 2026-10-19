import asyncio
import json

import pytest
from project_fakes import specification
from test_providers import GENERATION, REVIEW, FakeProcess, install_process

from autodev.config import CodexCLIConfig
from autodev.model_execution import capture_execution
from autodev.model_policy import ModelPolicy, resolve_policy
from autodev.providers import (
    CodexCLIProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderModelUnavailableError,
    ProviderRateLimitError,
)


@pytest.mark.parametrize(
    "method, role, response",
    [
        ("architect", "architect", specification().model_dump()),
        (
            "plan",
            "architect",
            {
                "summary": "plan",
                "tasks": [
                    {
                        "id": "one",
                        "description": "work",
                        "owned_files": ["one.py"],
                        "acceptance_criteria": ["works"],
                    }
                ],
            },
        ),
        ("generate_code", "developer", GENERATION),
        ("review", "reviewer", REVIEW),
    ],
)
def test_role_dispatch_and_exact_safe_argv(monkeypatch, method, role, response):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(json.dumps(response).encode()))
    policy = resolve_policy(ModelPolicy(overrides={"reviewer": {"reasoning_effort": "xhigh"}}))
    provider = CodexCLIProvider(CodexCLIConfig(), model_policy=policy)
    records = []
    args = ("task", [], 4) if method in {"plan", "architect"} else ("task", [], None)
    with capture_execution(records.append):
        asyncio.run(getattr(provider, method)(*args))
    command, options, _ = calls[0]
    settings = policy.for_role(role)
    assert command[command.index("--model") + 1] == settings.model
    assert f'model_reasoning_effort="{settings.reasoning_effort}"' in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert 'forced_login_method="chatgpt"' in command
    assert "--ignore-user-config" in command and "multi_agent" in command
    assert "--json" not in command and "--add-dir" not in command
    assert "shell" not in options
    assert records[0].role == role and records[0].status == "succeeded"
    assert records[0].requested == settings
    assert records[0].observed_model is None and records[0].observed_reasoning_effort is None
    assert records[0].observation_status == "unavailable"


@pytest.mark.parametrize(
    "diagnostic, code, error, kind",
    [
        (
            b"error: invalid reasoning_effort",
            1,
            ProviderConfigurationError,
            "configuration_invalid",
        ),
        (
            b"warning: unsupported reasoning; using default",
            0,
            ProviderConfigurationError,
            "configuration_invalid",
        ),
        (b"model_not_found secret-value", 1, ProviderModelUnavailableError, "model_unavailable"),
        (b"model is not available", 1, ProviderModelUnavailableError, "model_unavailable"),
        (
            b"error: model 'gpt-6-astra' is not available for this account",
            1,
            ProviderModelUnavailableError,
            "model_unavailable",
        ),
        (
            b"warning: requested model unavailable; falling back to default model",
            0,
            ProviderModelUnavailableError,
            "model_unavailable",
        ),
        (b"401 unauthorized secret-value", 1, ProviderAuthenticationError, "authentication"),
        (b"429 usage limit secret-value", 1, ProviderRateLimitError, "rate_limit"),
    ],
)
def test_explicit_failure_kinds_never_retry_or_substitute(
    monkeypatch, diagnostic, code, error, kind
):
    calls, _ = install_process(
        monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode(), diagnostic, code)
    )
    provider = CodexCLIProvider(CodexCLIConfig(), model_policy=resolve_policy(ModelPolicy()))
    records = []
    with capture_execution(records.append), pytest.raises(error) as failure:
        asyncio.run(provider.generate_code("task", [], None))
    assert len(calls) == 1
    assert failure.value.kind == records[0].error_kind == kind
    assert records[0].status == "failed"
    assert "secret-value" not in str(failure.value)


def test_parallel_execution_collectors_are_task_local(monkeypatch):
    install_process(monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode()))
    results = [[], []]

    async def run(index, preset):
        provider = CodexCLIProvider(
            CodexCLIConfig(), model_policy=resolve_policy(ModelPolicy(preset=preset))
        )
        with capture_execution(results[index].append):
            await provider.generate_code("task", [], None)

    async def both():
        await asyncio.gather(run(0, "fast"), run(1, "maximum_quality"))

    asyncio.run(both())
    assert [len(result) for result in results] == [1, 1]
    assert results[0][0].requested.reasoning_effort == "low"
    assert results[1][0].requested.reasoning_effort == "xhigh"
    assert results[0][0].call_id != results[1][0].call_id


def test_legacy_no_model_or_reasoning_flags(monkeypatch):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode()))
    asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert "--model" not in calls[0][0]
    assert not any("model_reasoning_effort" in value for value in calls[0][0])


def test_model_self_report_does_not_become_a_runtime_observation(monkeypatch):
    response = GENERATION | {"summary": "I used gpt-6-astra with xhigh reasoning"}
    install_process(monkeypatch, lambda: FakeProcess(json.dumps(response).encode()))
    records = []
    with capture_execution(records.append):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert records[0].observed_model is None and records[0].observed_reasoning_effort is None
