import csv
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

from autodev.runner import DEFAULT_PYTEST_COMMAND
from autodev.sandbox import (
    DEFAULT_RUFF_COMMAND,
    DockerSandbox,
    _run_bounded,
    _workspace_mount,
    infrastructure_failure_reason,
)


@pytest.mark.parametrize(
    "exit_code,timed_out",
    [(0, False), (1, False), (-1, True), (125, False), (126, False), (127, False)],
)
def test_docker_restrictions_and_cleanup(
    tmp_path: Path, monkeypatch, exit_code: int, timed_out: bool
) -> None:
    calls = []

    def fake_run(command: Sequence[str], timeout_seconds: int, max_output_chars: int):
        calls.append(list(command))
        if command[1] == "rm":
            return subprocess.CompletedProcess(command, 0, "", ""), False
        return subprocess.CompletedProcess(command, exit_code, "pytest output", ""), timed_out

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("autodev-sandbox:py311").run_pytest(
        tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100
    )

    run, cleanup = calls
    assert run[-len(DEFAULT_PYTEST_COMMAND) :] == DEFAULT_PYTEST_COMMAND
    for flag, value in (
        ("--network", "none"),
        ("--user", "65534:65534"),
        ("--cpus", "1"),
        ("--memory", "256m"),
        ("--memory-swap", "256m"),
        ("--pids-limit", "128"),
        ("--cap-drop", "ALL"),
        ("--security-opt", "no-new-privileges"),
        ("--log-driver", "none"),
        ("--pull", "never"),
    ):
        assert run[run.index(flag) + 1] == value
    assert "--read-only" in run
    assert run[run.index("--mount") + 1].endswith(",readonly")
    assert run[run.index("--tmpfs") + 1] == "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777"
    assert cleanup == ["docker", "rm", "--force", run[run.index("--name") + 1]]
    assert result.timed_out == timed_out
    assert result.passed == (exit_code == 0 and not timed_out)
    assert result.skipped == (exit_code in (125, 126, 127))
    assert result.stdout == "pytest output"


def test_missing_docker_disables_execution(tmp_path: Path, monkeypatch) -> None:
    def missing(*args):
        raise FileNotFoundError("docker missing")

    monkeypatch.setattr("autodev.sandbox._run_bounded", missing)
    result = DockerSandbox("image").run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100)

    assert result.skipped
    assert not result.passed
    assert "unavailable" in result.reason
    assert result.infrastructure_failed


def test_cleanup_failure_prevents_success(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, *args):
        code = 1 if command[1] == "rm" else 0
        return subprocess.CompletedProcess(command, code, "", "daemon unavailable"), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("image").run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100)

    assert result.skipped
    assert not result.passed
    assert "cleanup failed" in result.reason
    assert result.infrastructure_failed


@pytest.mark.parametrize(
    "command,code,output",
    [
        (DEFAULT_PYTEST_COMMAND, 2, "ModuleNotFoundError: No module named 'dotenv'"),
        (DEFAULT_PYTEST_COMMAND, 2, "ModuleNotFoundError: No module named 'pydantic'"),
        (DEFAULT_RUFF_COMMAND, 1, "/usr/local/bin/python: No module named ruff"),
        (
            DEFAULT_PYTEST_COMMAND,
            1,
            "FileNotFoundError: [Errno 2] No such file or directory: 'git'",
        ),
        (DEFAULT_PYTEST_COMMAND, 1, "Error response from daemon: invalid mount config"),
        (DEFAULT_PYTEST_COMMAND, 1, "exec: python: executable file not found in $PATH"),
        (DEFAULT_PYTEST_COMMAND, 125, "container startup failed"),
        (DEFAULT_PYTEST_COMMAND, 127, "executable missing"),
        (DEFAULT_PYTEST_COMMAND, 137, "killed"),
        (DEFAULT_PYTEST_COMMAND, 3, "INTERNALERROR"),
        (DEFAULT_PYTEST_COMMAND, 4, "file or directory not found: tests"),
        (DEFAULT_PYTEST_COMMAND, 5, "no tests ran"),
        (DEFAULT_RUFF_COMMAND, 2, "unexpected argument"),
    ],
)
def test_infrastructure_failure_classification(tmp_path, monkeypatch, command, code, output):
    def fake_run(arguments, *args):
        if arguments[1] == "rm":
            return subprocess.CompletedProcess(arguments, 0, "", ""), False
        return subprocess.CompletedProcess(arguments, code, "", output), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    sandbox = DockerSandbox("image")
    result = sandbox._run_command(tmp_path, command, 30, 20000)
    assert result.infrastructure_failed
    assert not result.passed
    assert result.reason


@pytest.mark.parametrize(
    "command,code,output",
    [
        (DEFAULT_PYTEST_COMMAND, 1, "AssertionError: assert 1 == 2"),
        (DEFAULT_PYTEST_COMMAND, 2, "ModuleNotFoundError: No module named 'parallel_text'"),
        (DEFAULT_PYTEST_COMMAND, 2, "ModuleNotFoundError: No module named 'autodev.missing'"),
        (DEFAULT_PYTEST_COMMAND, 2, "SyntaxError: invalid syntax"),
        (
            DEFAULT_PYTEST_COMMAND,
            1,
            "FileNotFoundError: [Errno 2] No such file or directory: 'data.csv'",
        ),
        (DEFAULT_RUFF_COMMAND, 1, "module.py:1: F821 Undefined name"),
    ],
)
def test_genuine_code_failures_are_not_infrastructure(command, code, output):
    assert infrastructure_failure_reason(command, code, output) is None


def test_environment_probe_failure_is_infrastructure_even_for_stale_image(tmp_path, monkeypatch):
    def fake_run(arguments, *args):
        if arguments[1] == "rm":
            return subprocess.CompletedProcess(arguments, 0, "", ""), False
        return subprocess.CompletedProcess(
            arguments, 2, "", "can't open check_environment.py"
        ), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("old-image").check_environment(tmp_path, 30, 20000)
    assert result.infrastructure_failed
    assert "rebuild" in result.reason


def test_environment_probe_timeout_is_infrastructure(tmp_path, monkeypatch):
    def fake_run(arguments, *args):
        return subprocess.CompletedProcess(arguments, 0, "", ""), arguments[1] == "run"

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("image").check_environment(tmp_path, 30, 20000)
    assert result.infrastructure_failed and result.timed_out


def test_already_removed_container_is_not_a_cleanup_failure(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, *args):
        if command[1] == "rm":
            return subprocess.CompletedProcess(command, 1, "", "No such container: name"), False
        return subprocess.CompletedProcess(command, 0, "", ""), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("image").run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100)

    assert result.passed


def test_interruption_still_removes_container(tmp_path: Path, monkeypatch) -> None:
    calls = []

    def interrupted(command, *args):
        calls.append(list(command))
        if command[1] == "run":
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(command, 0, "", ""), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", interrupted)
    with pytest.raises(KeyboardInterrupt):
        DockerSandbox("image").run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100)

    assert calls[1] == ["docker", "rm", "--force", calls[0][calls[0].index("--name") + 1]]


def test_cleanup_timeout_prevents_success(tmp_path: Path, monkeypatch) -> None:
    def fake_run(command, *args):
        return subprocess.CompletedProcess(command, 0, "", ""), command[1] == "rm"

    monkeypatch.setattr("autodev.sandbox._run_bounded", fake_run)
    result = DockerSandbox("image").run_pytest(tmp_path, DEFAULT_PYTEST_COMMAND, 30, 100)

    assert result.skipped
    assert not result.passed
    assert "cleanup timed out" in result.reason


def test_workspace_mount_quotes_comma_in_source_path(tmp_path: Path) -> None:
    mount = _workspace_mount(tmp_path / "comma,name")
    fields = next(csv.reader([mount]))

    assert fields == [
        "type=bind",
        f"src={(tmp_path / 'comma,name').resolve()}",
        "dst=/workspace",
        "readonly",
    ]


def test_output_is_bounded_and_invalid_utf8_is_replaced() -> None:
    # This is a fixed, trusted test fixture, never model-generated source.
    command = [
        sys.executable,
        "-c",
        "import os; os.write(1, b'\\xff' * 100000); os.write(2, b'e' * 100000)",
    ]
    completed, timed_out = _run_bounded(command, 10, 100)

    assert completed.returncode == 0
    assert not timed_out
    assert completed.stdout.startswith("\ufffd" * 100)
    assert completed.stderr.startswith("e" * 100)
    assert len(completed.stdout) < 150
    assert len(completed.stderr) < 150
    assert "truncated" in completed.stdout


def test_timeout_kills_cli_process() -> None:
    completed, timed_out = _run_bounded(
        [sys.executable, "-c", "import time; time.sleep(60)"], 1, 100
    )

    assert timed_out
    assert completed.returncode != 0
