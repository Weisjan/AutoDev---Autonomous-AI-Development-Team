"""Offline regressions for the documented Codex final-message transport."""

import asyncio
import json
import re

import pytest
from project_fakes import ProjectModels, project_repository, specification, workflow
from test_providers import FakeProcess, install_process

from autodev.architect import ProjectArchitect
from autodev.config import AutoDevConfig, CodexCLIConfig
from autodev.project_models import ProjectSpec
from autodev.providers import (
    CodexCLIProvider,
    ProviderJSONParseError,
    ProviderSchemaError,
    _parse_response,
    _strict_schema,
)
from autodev.schemas import GeneratedFile


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{",
        b"```json\n{}\n```",
        b"\xff",
        b'{"secret-value": NaN}',
        b'{"type":"thread.started"}\n{"type":"turn.completed"}\n',
    ],
)
def test_malformed_json_is_distinct_from_schema_failure(payload):
    with pytest.raises(ProviderJSONParseError, match="json_parse") as error:
        _parse_response(payload, ProjectSpec)
    assert "secret-value" not in str(error.value)


def test_valid_project_json_roundtrips():
    spec = specification()
    assert _parse_response(spec.model_dump_json(indent=2).encode(), ProjectSpec) == spec


@pytest.mark.parametrize(
    "change, expected",
    [
        ("missing", "title [missing]"),
        ("type", "title [string_type]"),
        ("test_path", "milestones.2.test_paths.0 [string_pattern_mismatch]"),
        ("cycle", "root [value_error:dependency_cycle]"),
        ("extra", "<extra> [extra_forbidden]"),
        ("reserved", "tasks.0.owned_files [value_error:unsafe_project_path]"),
    ],
)
def test_valid_json_schema_diagnostics_are_specific_and_redacted(change, expected):
    data = specification().model_dump()
    if change == "missing":
        del data["title"]
    elif change == "type":
        data["title"] = {"secret-value": "private-input"}
    elif change == "test_path":
        data["milestones"][2]["test_paths"] = ["tests/secret-value/"]
    elif change == "cycle":
        data["tasks"][0]["depends_on"] = ["utility"]
        data["tasks"][1]["depends_on"] = ["foundation"]
    elif change == "extra":
        data["secret-value"] = "private-input"
    else:
        data["tasks"][0]["owned_files"] = ["CON.py"]
    with pytest.raises(ProviderSchemaError, match="valid JSON") as error:
        _parse_response(json.dumps(data).encode(), ProjectSpec)
    assert expected in str(error.value)
    assert "secret-value" not in str(error.value)
    assert "private-input" not in str(error.value)


@pytest.mark.parametrize(
    "path, valid",
    [
        ("tests/test_app.py", True),
        ("tests/domain/test_invoice.py", True),
        ("tests/", False),
        ("tests/*.py", False),
        ("tests/test_app.py::test_one", False),
        ("../tests/test_app.py", False),
        ("pytest tests/test_app.py", False),
        ("tests/.hidden.py", False),
        ("tests/test_app.py;whoami", False),
    ],
)
def test_advertised_schema_enforces_exact_test_file_syntax(path, valid):
    schema = _strict_schema(ProjectSpec)
    for definition in ("ProjectTask", "Milestone"):
        item = schema["$defs"][definition]["properties"]["test_paths"]["items"]
        assert bool(re.fullmatch(item["pattern"], path)) is valid
        assert "existing trusted" in item["description"]
    assert schema["$defs"]["ProjectTask"]["properties"]["owned_files"]["maxItems"] == 10


def test_cli_final_json_with_progress_on_stderr_and_architect_only_prompt(monkeypatch):
    spec = specification()
    calls, processes = install_process(
        monkeypatch,
        lambda: FakeProcess(
            spec.model_dump_json(indent=2).encode(),
            b"OpenAI Codex v0.162.0\nthinking\nPlanning repository\ntokens used\n1000\n",
        ),
    )
    files = [
        GeneratedFile(path=p, content="# trusted context")
        for p in (
            "tests/test_base.py",
            "tests/test_utility.py",
            "tests/test_app.py",
        )
    ]
    provider = CodexCLIProvider(CodexCLIConfig())
    result = asyncio.run(ProjectArchitect(provider, 4).design("Build a repository", files))
    assert result == spec
    command, _, schema = calls[0]
    assert "--output-schema" in command and "--json" not in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert schema["properties"]["execution_profile"]["const"] == "python"
    prompt = processes[0].stdin.write.call_args.args[0].decode()
    assert "Trusted test files:" in prompt and '"tests/test_app.py"' in prompt
    assert "Return all files" not in prompt
    assert "FILE paths only" in prompt
    assert len(calls) == 1


@pytest.mark.parametrize("schema_failure", [False, True])
def test_architect_failure_report_stops_before_developers_without_implicit_retry(
    tmp_path,
    monkeypatch,
    schema_failure,
):
    repo = project_repository(tmp_path / "repository")
    models = ProjectModels()
    instance = workflow(AutoDevConfig(), repo, models)
    payload = specification().model_dump()
    payload["milestones"][2]["test_paths"] = ["tests/"]
    # Install the subprocess mock after Git preparation: only the model call is mocked.
    real_spawn = asyncio.create_subprocess_exec
    calls, _ = install_process(
        monkeypatch,
        lambda: FakeProcess(
            json.dumps(payload).encode() if schema_failure else b'{"title":',
        ),
    )
    codex_spawn = asyncio.create_subprocess_exec

    async def spawn(*args, **kwargs):
        if args[0] == "codex.exe":
            return await codex_spawn(*args, **kwargs)
        return await real_spawn(*args, **kwargs)

    monkeypatch.setattr("autodev.providers.asyncio.create_subprocess_exec", spawn)
    # Git uses its own subprocess API; the Codex call alone uses this mock.
    instance.architect = ProjectArchitect(CodexCLIProvider(CodexCLIConfig()), 4)
    report = asyncio.run(instance.run_task("Build a repository"))
    assert not report.succeeded and report.integration_status == "failed"
    assert report.specification is None and report.tasks == []
    assert report.model_calls_reserved == 1 and len(calls) == 1
    assert report.planner_execution.error == report.stopped_reason
    assert ("schema validation" if schema_failure else "json_parse") in report.stopped_reason
    assert models.calls == []
    assert not report.checkpoint_history
