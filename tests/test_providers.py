import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from autodev.config import AutoDevConfig, CodexCLIConfig
from autodev.orchestrator import build_orchestrator
from autodev.providers import (
    CodexCLIProvider,
    OpenAIAPIProvider,
    ProviderAuthenticationError,
    ProviderProcessError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
    _codex_environment,
    _codex_executable,
    _strict_schema,
    build_provider,
)
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as RunResult

GENERATION = {
    "summary": "Implemented add",
    "files": [{"path": "calculator.py", "content": "def add(a, b):\n    return a + b\n"}],
    "assumptions": [],
}
REVIEW = {"approved": True, "risk_level": "low", "summary": "OK", "findings": []}


class FakeProcess:
    """Pipe-compatible subprocess; no executable or network is used."""

    def __init__(self, stdout: bytes, stderr: bytes = b"", exit_code: int = 0, hang=False):
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.stdout.feed_data(stdout)
        self.stderr.feed_data(stderr)
        if not hang:
            self.stdout.feed_eof()
            self.stderr.feed_eof()
        self.stdin = Mock()
        self.stdin.drain = AsyncMock()
        self.returncode = None
        self.exit_code = exit_code
        self.hang = hang
        self.killed = False
        self.reaped = False

    async def wait(self):
        if self.hang:
            await asyncio.Future()
        self.returncode = self.exit_code
        self.reaped = True
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def communicate(self):
        self.reaped = True
        return await self.stdout.read(), await self.stderr.read()


def install_process(monkeypatch, factory):
    calls = []
    processes = []

    async def spawn(*args, **kwargs):
        schema_path = Path(args[args.index("--output-schema") + 1])
        calls.append((args, kwargs, json.loads(schema_path.read_text(encoding="utf-8"))))
        process = factory()
        processes.append(process)
        return process

    monkeypatch.setattr("autodev.providers._codex_executable", lambda _: "codex.exe")
    monkeypatch.setattr("autodev.providers.asyncio.create_subprocess_exec", spawn)
    return calls, processes


def test_default_and_opt_in_provider_selection():
    assert isinstance(build_provider(AutoDevConfig()), CodexCLIProvider)
    assert isinstance(build_provider(AutoDevConfig(provider="openai_api")), OpenAIAPIProvider)


def test_codex_planner_uses_validated_task_schema(monkeypatch):
    plan = {
        "summary": "one task",
        "tasks": [
            {
                "id": "one",
                "description": "Implement",
                "owned_files": ["one.py"],
                "acceptance_criteria": ["one function exists"],
            }
        ],
    }
    calls, processes = install_process(monkeypatch, lambda: FakeProcess(json.dumps(plan).encode()))
    result = asyncio.run(CodexCLIProvider(CodexCLIConfig()).plan("request", [], 2))
    assert result.tasks[0].owned_files == ["one.py"]
    assert "tasks" in calls[0][2]["properties"]
    assert "at most 2" in processes[0].stdin.write.call_args.args[0].decode()


def test_codex_parallel_call_runs_read_only_in_assigned_worktree(tmp_path, monkeypatch):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode()))
    provider = CodexCLIProvider(CodexCLIConfig(), workspace=tmp_path)
    asyncio.run(provider.generate_code("task", [], None))
    assert calls[0][1]["cwd"] == tmp_path
    assert calls[0][0][calls[0][0].index("--sandbox") + 1] == "read-only"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("diagnostic", [b"429", b"rate limit", b"usage limit reached"])
def test_codex_rate_limits_do_not_fallback_or_retry(monkeypatch, diagnostic):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(b"", diagnostic, 1))
    with pytest.raises(ProviderRateLimitError, match="no paid fallback"):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert len(calls) == 1


def test_codex_generation_uses_read_only_chatgpt_and_validated_json(monkeypatch):
    calls, processes = install_process(
        monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode())
    )
    previous = [GeneratedFile(path="calculator.py", content="return a - b")]
    provider = CodexCLIProvider(CodexCLIConfig(), developer_model="example-model")
    result = asyncio.run(provider.generate_code("Implement add & $(whoami)", previous, "failed"))
    assert result == CodeGenerationResult.model_validate(GENERATION)
    command, options, schema = calls[0]
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert command[command.index("--model") + 1] == "example-model"
    assert 'forced_login_method="chatgpt"' in command
    assert 'model_provider="openai"' in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--ephemeral" in command
    assert "shell_tool" in command
    assert "multi_agent" in command
    assert "--output-last-message" not in command
    assert "--dangerously-bypass-approvals-and-sandbox" not in command
    assert "--add-dir" not in command
    assert command[-1] == "-"
    assert not any("$(whoami)" in part for part in command)
    prompt = processes[0].stdin.write.call_args.args[0].decode()
    assert "$(whoami)" in prompt
    assert "return a - b" in prompt
    assert "failed" in prompt
    assert set(schema["required"]) == {"summary", "files", "assumptions"}
    assert schema["additionalProperties"] is False
    assert "shell" not in options
    assert options["cwd"] != Path.cwd()
    assert not options["cwd"].exists()  # Temporary schema directory cleaned up.
    assert not (Path.cwd() / "calculator.py").exists()
    assert processes[0].reaped


def test_codex_reviewer_receives_files_and_separate_schema_and_model(monkeypatch):
    calls, processes = install_process(
        monkeypatch, lambda: FakeProcess(json.dumps(REVIEW).encode())
    )
    provider = CodexCLIProvider(CodexCLIConfig(), reviewer_model="review-model")
    result = asyncio.run(
        provider.review("review add", [GeneratedFile(**GENERATION["files"][0])], None)
    )
    assert result == ReviewResult.model_validate(REVIEW)
    command, _, schema = calls[0]
    assert command[command.index("--model") + 1] == "review-model"
    assert "approved" in schema["properties"]
    assert "def add" in processes[0].stdin.write.call_args.args[0].decode()


@pytest.mark.parametrize(
    "output",
    [
        b"",
        b"not JSON",
        b"{}",
        b'{"summary": "x", "files": [], "unexpected": 1}',
        json.dumps(GENERATION | {"files": [{"path": "../escape.py", "content": "bad"}]}).encode(),
        json.dumps(GENERATION | {"files": [{"path": "C:/escape.py", "content": "bad"}]}).encode(),
        b"\xff",
        b"```json\n{}\n```",
    ],
)
def test_codex_rejects_malformed_and_unsafe_responses(monkeypatch, output):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(output))
    with pytest.raises(ProviderResponseError):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert len(calls) == 1


def test_codex_reviewer_rejects_coerced_boolean(monkeypatch):
    install_process(
        monkeypatch, lambda: FakeProcess(json.dumps(REVIEW | {"approved": "yes"}).encode())
    )
    with pytest.raises(ProviderResponseError):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).review("task", [], None))


@pytest.mark.parametrize(
    "diagnostic",
    [
        b"401 Unauthorized secret-value",
        b"not logged in",
        b"ChatGPT login required",
        b"authentication failed",
        b"refresh token expired secret-value",
    ],
)
def test_codex_authentication_failure_is_safe_and_does_not_fallback(monkeypatch, diagnostic):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(b"", diagnostic, 1))
    monkeypatch.setattr("autodev.providers.OpenAIAPIProvider", Mock(side_effect=AssertionError))
    with pytest.raises(ProviderAuthenticationError, match="codex login") as error:
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert "secret-value" not in str(error.value)
    assert len(calls) == 1


def test_codex_nonzero_exit_is_not_accepted_even_with_valid_json(monkeypatch):
    install_process(monkeypatch, lambda: FakeProcess(json.dumps(GENERATION).encode(), b"crash", 9))
    with pytest.raises(ProviderProcessError, match="code 9"):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))


def test_codex_timeout_kills_and_reaps_process(monkeypatch):
    _, processes = install_process(monkeypatch, lambda: FakeProcess(b"", hang=True))
    # Avoid waiting one second per test; the validated config remains positive.
    original = asyncio.wait_for

    async def fast_wait(awaitable, timeout):
        return await original(awaitable, timeout=0.01)

    monkeypatch.setattr("autodev.providers.asyncio.wait_for", fast_wait)
    with pytest.raises(ProviderTimeoutError):
        asyncio.run(
            CodexCLIProvider(CodexCLIConfig(timeout_seconds=1)).generate_code("task", [], None)
        )
    assert processes[0].killed
    assert processes[0].reaped


def test_codex_cancellation_kills_and_reaps_process(monkeypatch):
    _, processes = install_process(monkeypatch, lambda: FakeProcess(b"", hang=True))

    async def cancel():
        call = asyncio.create_task(
            CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None)
        )
        while not processes:
            await asyncio.sleep(0)
        call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call

    asyncio.run(cancel())
    assert processes[0].killed
    assert processes[0].reaped


def test_codex_output_limit_is_bounded(monkeypatch):
    _, processes = install_process(monkeypatch, lambda: FakeProcess(b"x" * 200, hang=True))
    with pytest.raises(ProviderResponseError, match="output limit"):
        asyncio.run(
            CodexCLIProvider(CodexCLIConfig(max_output_bytes=100)).generate_code("task", [], None)
        )
    assert processes[0].killed
    assert processes[0].reaped


def test_codex_start_failure(monkeypatch):
    monkeypatch.setattr("autodev.providers._codex_executable", lambda _: "codex.exe")
    monkeypatch.setattr(
        "autodev.providers.asyncio.create_subprocess_exec", AsyncMock(side_effect=OSError("secret"))
    )
    with pytest.raises(ProviderProcessError, match="Could not start") as error:
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert "secret" not in str(error.value)


def test_codex_broken_stdin_still_classifies_authentication_error(monkeypatch):
    def factory():
        process = FakeProcess(b"", b"authentication failed", 1)
        process.stdin.drain.side_effect = BrokenPipeError
        return process

    install_process(monkeypatch, factory)
    with pytest.raises(ProviderAuthenticationError):
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))


def test_codex_pipe_failure_kills_process_and_omits_raw_error(monkeypatch):
    def factory():
        process = FakeProcess(b"", hang=True)
        process.stdout.read = AsyncMock(side_effect=OSError("private diagnostic"))
        # communicate is cleanup only, after the failed reader has been cancelled.
        process.communicate = AsyncMock(return_value=(b"", b""))
        return process

    _, processes = install_process(monkeypatch, factory)
    with pytest.raises(ProviderProcessError, match="communication failed") as error:
        asyncio.run(CodexCLIProvider(CodexCLIConfig()).generate_code("task", [], None))
    assert "private diagnostic" not in str(error.value)
    assert processes[0].killed
    processes[0].communicate.assert_awaited_once()


def test_codex_missing_executable(monkeypatch):
    monkeypatch.setattr("autodev.providers.shutil.which", lambda _: None)
    with pytest.raises(ProviderProcessError, match="not found"):
        _codex_executable("codex")


@pytest.mark.parametrize("package", ["codex", "codex-win32-x64"])
def test_windows_npm_launcher_resolves_native_binary(tmp_path, monkeypatch, package):
    launcher = tmp_path / "codex.cmd"
    native = (
        tmp_path
        / "node_modules"
        / "@openai"
        / package
        / "vendor"
        / "x86_64-pc-windows-msvc"
        / "codex"
        / "codex.exe"
    )
    native.parent.mkdir(parents=True)
    native.touch()
    monkeypatch.setattr("autodev.providers.shutil.which", lambda _: str(launcher))
    monkeypatch.setattr("autodev.providers.sys.platform", "win32")
    assert _codex_executable("codex") == str(native)


def test_windows_launcher_fails_without_shell_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr("autodev.providers.shutil.which", lambda _: str(tmp_path / "codex.cmd"))
    monkeypatch.setattr("autodev.providers.sys.platform", "win32")
    with pytest.raises(ProviderProcessError, match="native Windows binary"):
        _codex_executable("codex")


def test_codex_environment_never_reads_or_copies_authentication_values(monkeypatch):
    class GuardedEnvironment(dict):
        def __getitem__(self, name):
            assert name not in {"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_AUTH_TOKEN"}
            return super().__getitem__(name)

    monkeypatch.setattr(
        "autodev.providers.os.environ",
        GuardedEnvironment(
            {
                "PATH": "bin",
                "CODEX_HOME": "existing-login-directory",
                "USERPROFILE": "user",
                "OPENAI_API_KEY": "unread",
                "CODEX_API_KEY": "unread",
                "CODEX_AUTH_TOKEN": "unread",
            }
        ),
    )
    assert _codex_environment() == {
        "PATH": "bin",
        "CODEX_HOME": "existing-login-directory",
        "USERPROFILE": "user",
    }


def test_strict_schema_makes_nested_nullable_fields_required():
    schema = _strict_schema(ReviewResult)
    finding = schema["$defs"]["ReviewFinding"]
    assert set(finding["required"]) == {"severity", "message", "file_path", "line"}
    assert finding["additionalProperties"] is False
    assert {"type": "null"} in finding["properties"]["line"]["anyOf"]


def test_optional_api_adapter_preserves_existing_clients(monkeypatch):
    developer = AsyncMock(return_value=CodeGenerationResult.model_validate(GENERATION))
    reviewer = AsyncMock(return_value=ReviewResult.model_validate(REVIEW))
    monkeypatch.setattr("autodev.providers.OpenAIDeveloperClient.generate_code", developer)
    monkeypatch.setattr("autodev.providers.OpenAIReviewerClient.review", reviewer)
    provider = build_provider(AutoDevConfig(provider="openai_api"))
    assert asyncio.run(provider.generate_code("task", [], None)).files
    assert asyncio.run(provider.review("task", [], None)).approved
    developer.assert_awaited_once_with("task", [], None)
    reviewer.assert_awaited_once_with("task", [], None)


def test_optional_api_missing_dependency_is_actionable(monkeypatch):
    monkeypatch.setattr(
        "autodev.providers.OpenAIDeveloperClient.generate_code",
        AsyncMock(side_effect=ImportError("agents")),
    )
    with pytest.raises(ProviderProcessError, match="openai_api.*requires"):
        asyncio.run(
            build_provider(AutoDevConfig(provider="openai_api")).generate_code("task", [], None)
        )


def test_codex_agents_run_through_workspace_test_and_review(tmp_path, monkeypatch):
    responses = iter([GENERATION, REVIEW])
    calls, _ = install_process(
        monkeypatch, lambda: FakeProcess(json.dumps(next(responses)).encode())
    )
    sandbox = Mock()
    sandbox.run_pytest.return_value = RunResult(command=["pytest"], exit_code=0, stdout="1 passed")
    monkeypatch.setattr("autodev.orchestrator.build_sandbox", lambda _: sandbox)
    config = AutoDevConfig(workspace_dir=tmp_path / "workspace")
    result = asyncio.run(build_orchestrator(config).run_task("Implement add"))
    assert result.succeeded
    assert result.model_calls_reserved == 2
    assert (config.workspace_dir / "calculator.py").read_text() == GENERATION["files"][0]["content"]
    assert len(calls) == 2
    sandbox.run_pytest.assert_called_once()


def test_codex_cannot_rewrite_protected_tests_or_write_partial_batch(tmp_path, monkeypatch):
    malicious = GENERATION | {
        "files": GENERATION["files"]
        + [
            {"path": "tests/test_fixed.py", "content": "tampered"},
        ]
    }
    responses = iter([malicious, REVIEW])
    install_process(monkeypatch, lambda: FakeProcess(json.dumps(next(responses)).encode()))
    sandbox = Mock()
    monkeypatch.setattr("autodev.orchestrator.build_sandbox", lambda _: sandbox)
    seed = tmp_path / "seed"
    seed.mkdir()
    (seed / "test_fixed.py").write_text("assert True\n")
    config = AutoDevConfig(workspace_dir=tmp_path / "workspace")
    result = asyncio.run(build_orchestrator(config).run_task("Implement add", seed_tests_dir=seed))
    assert not result.succeeded
    assert "protected path" in result.stopped_reason
    assert (config.workspace_dir / "tests/test_fixed.py").read_text() == "assert True\n"
    assert not (config.workspace_dir / "calculator.py").exists()
    sandbox.run_pytest.assert_not_called()


def test_codex_failure_stops_before_tests_or_review_and_never_uses_api(tmp_path, monkeypatch):
    calls, _ = install_process(monkeypatch, lambda: FakeProcess(b"bad response"))
    monkeypatch.setattr("autodev.providers.OpenAIAPIProvider", Mock(side_effect=AssertionError))
    sandbox = Mock()
    monkeypatch.setattr("autodev.orchestrator.build_sandbox", lambda _: sandbox)
    config = AutoDevConfig(workspace_dir=tmp_path / "workspace")
    with pytest.raises(ProviderResponseError):
        asyncio.run(build_orchestrator(config).run_task("Implement add"))
    assert len(calls) == 1
    assert list(config.workspace_dir.iterdir()) == []
    sandbox.run_pytest.assert_not_called()
