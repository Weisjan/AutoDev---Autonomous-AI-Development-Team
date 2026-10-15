import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from web_fakes import git, repository, workflow_factory  # noqa: E402

from autodev.config import AutoDevConfig  # noqa: E402
from autodev.parallel import SandboxChecks  # noqa: E402
from autodev.parallel_schemas import ParallelWorkflowReport  # noqa: E402
from autodev.planning import DevelopmentTask, TaskPlan  # noqa: E402
from autodev.web.app import create_app  # noqa: E402
from autodev.web.models import StartRun  # noqa: E402
from autodev.web.security import contained, redact  # noqa: E402
from autodev.web.service import RunService  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    return repository(tmp_path / "repo")


@pytest.fixture
def client(repo):
    app = create_app([repo], factory=workflow_factory)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000)) as client:
        token = client.get("/api/session").json()["csrf"]
        client.headers["X-AutoDev-CSRF"] = token
        yield client


def payload(client, **overrides):
    return {
        "repository_id": client.get("/api/projects").json()[0]["id"],
        "instructions": "Implement two independent Python modules",
        **overrides,
    }


def test_api_real_orchestrator_git_lifecycle_and_report(client, repo):
    original = git(repo, "rev-parse", "HEAD")
    started = client.post("/api/runs", json=payload(client))
    assert started.status_code == 202
    key = started.json()["id"]
    assert client.post("/api/runs", json=payload(client)).status_code == 409
    # Wait in the server event loop; deterministic bounded completion, no model/network calls.
    client.portal.call(lambda: asyncio.gather(*client.app.state.service.tasks.values()))
    result = client.get(f"/api/runs/{key}").json()
    assert result["status"] == "succeeded"
    assert len(result["report"]["tasks"]) == 2
    assert result["report"]["rounds"][0]["checks"]["pytest"]["passed"] is True
    assert {e["stage"] for e in result["events"]} >= {
        "planning",
        "developer_started",
        "integrating",
        "validating",
        "reviewing",
        "finished",
    }
    assert git(repo, "rev-parse", "HEAD") == original
    assert git(repo, "branch", "--show-current") == "main"
    assert client.get(f"/api/runs/{key}/report").json()["succeeded"]
    files = client.get(f"/api/runs/{key}/files").json()
    assert {f["path"] for f in files} == {"module0.py", "module1.py"}
    assert "value =" in client.get(f"/api/runs/{key}/files/{files[0]['id']}").text
    assert client.get(f"/api/runs/{key}/files/not-owned").status_code == 404
    assert client.get("/api/runs").json()[0]["status"] == "succeeded"
    restored = RunService([repo], AutoDevConfig())
    asyncio.run(restored.initialize())
    assert restored.records[key]["events"] == result["events"]
    assert restored.records[key]["status"] == "succeeded"


@pytest.mark.parametrize(
    "changes",
    [
        {"repository_id": "../../outside"},
        {"repository_id": "0" * 12},
        {"concurrency": 3},
        {"max_corrections": 4},
        {"max_tasks": 9},
        {"max_model_calls": 100},
        {"workflow_timeout_seconds": 99999},
        {"instructions": "   "},
        {"instructions": "x" * 20001},
        {"provider": "openai_api"},
        {"command": "powershell.exe"},
        {"repository_path": "C:/"},
    ],
)
def test_validation_rejects_unsafe_browser_inputs(client, changes):
    assert client.post("/api/runs", json=payload(client, **changes)).status_code in {404, 422}
    assert not client.app.state.service.tasks


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example"},
        {"Host": "evil.example"},
        {"Sec-Fetch-Site": "cross-site"},
        {"X-AutoDev-CSRF": "wrong"},
    ],
)
def test_browser_security(client, headers):
    response = client.post("/api/runs", json=payload(client), headers=headers)
    assert response.status_code == 403
    assert not client.app.state.service.tasks


def test_unauthenticated_remote_and_oversized_requests(client, repo):
    client.cookies.clear()
    assert client.get("/api/runs").status_code == 401
    with TestClient(
        create_app([repo]), base_url="http://127.0.0.1", client=("10.0.0.2", 123)
    ) as remote:
        assert remote.get("/api/session").status_code == 403
    client.get("/api/session")
    assert client.post("/api/runs", json={"instructions": "x" * 41000}).status_code == 413


def test_settings_no_secrets_or_api_provider(client):
    result = client.get("/api/settings")
    assert result.json()["provider"] == "codex_cli"
    assert result.headers["Cache-Control"] == "no-store"
    assert "api_key" not in result.text
    assert client.post("/api/merge", json={}).status_code == 404


def test_cancellation_before_start_and_single_active_guard(repo):
    started = []

    def factory(config, root):
        assert config.provider == "codex_cli"
        assert config.sandbox.backend == "docker"
        workflow = SimpleNamespace(
            integration=SimpleNamespace(run_id="a" * 12),
            run_task=AsyncMock(side_effect=AssertionError("Must not start")),
        )
        started.append(workflow)
        return workflow

    async def exercise():
        service = RunService([repo], AutoDevConfig(provider="openai_api"), factory)
        request = StartRun(
            repository_id=next(iter(service.repositories)), instructions="Build modules"
        )
        record = await service.start(request)
        with pytest.raises(RuntimeError, match="already active"):
            await service.start(request)
        await service.cancel(record["id"])
        await service.shutdown()
        await asyncio.sleep(0)
        assert record["status"] == "cancelled"
        started[0].run_task.assert_not_awaited()

    asyncio.run(exercise())


def test_cancel_active_workflow_retains_cancelled_report(client):
    key = client.post("/api/runs", json=payload(client)).json()["id"]
    result = client.post(f"/api/runs/{key}/cancel", json={})
    assert result.status_code == 200
    client.portal.call(
        lambda: asyncio.gather(*client.app.state.service.tasks.values(), return_exceptions=True)
    )
    assert client.get(f"/api/runs/{key}").json()["status"] == "cancelled"


def test_report_import_and_interrupted_recovery(repo):
    service = RunService([repo], AutoDevConfig())
    identifier = next(iter(service.repositories))
    run_id = "a" * 12
    record = {
        "id": f"{identifier}:{run_id}",
        "run_id": run_id,
        "repository_id": identifier,
        "status": "running",
        "stage": "planning",
        "started_at": "2026-01-01",
        "instructions": "Build modules",
        "report": None,
        "events": [],
    }
    service.persist(record)
    asyncio.run(service.initialize())
    assert service.records[record["id"]]["status"] == "interrupted"
    report = ParallelWorkflowReport(
        request="Previous run",
        run_id=run_id,
        started_at="2026-01-01",
        finished_at="2026-01-02",
        integration_status="reviewed",
        succeeded=True,
        integration_branch="autodev/test/integration",
        integration_worktree="ignored-browser-path",
    )
    folder = repo / ".autodev/runs" / run_id
    folder.mkdir(parents=True)
    data = report.model_dump_json()
    (folder / "report.json").write_text(data)
    asyncio.run(service.initialize())
    assert service.records[record["id"]]["status"] == "succeeded"
    assert (folder / "report.json").read_text() == data


def test_repository_allowlist_and_traversal(repo, tmp_path):
    for path in [tmp_path, Path(repo.anchor)]:
        with pytest.raises(ValueError):
            RunService([path], AutoDevConfig())
    for path in ["../outside", "../../secret", str(tmp_path / "unrelated.txt")]:
        with pytest.raises(ValueError):
            contained(repo, path)


def test_redaction():
    assert redact({"access_token": "synthetic", "safe": "Bearer synthetic-token"}) == {
        "access_token": "[REDACTED]",
        "safe": "Bearer [REDACTED]",
    }
    assert "synthetic" not in redact("api_key=synthetic password='synthetic'")


def test_report_paths_cannot_select_unrelated_files(repo, tmp_path):
    service = RunService([repo], AutoDevConfig())
    identifier = next(iter(service.repositories))
    run_id = "b" * 12
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (unrelated / "module.py").write_text("private user content")
    report = ParallelWorkflowReport(
        request="Test output scope",
        run_id=run_id,
        started_at="2026-01-01",
        integration_branch="autodev/test",
        integration_worktree=str(unrelated),
        plan=TaskPlan(
            summary="one module",
            tasks=[
                DevelopmentTask(
                    id="module",
                    description="module",
                    owned_files=["module.py"],
                    acceptance_criteria=["works"],
                )
            ],
        ),
    )
    record = service.record(identifier, report)
    service.records[record["id"]] = record
    assert service.files(record["id"]) == []
    with pytest.raises(KeyError):
        service.read_file(record["id"], "module.py")
    with pytest.raises(ValueError):
        service.file_path(record, "../module.py")


def test_symlink_artifact_directory_is_rejected(repo, tmp_path):
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    link = repo / "link"
    try:
        link.symlink_to(unrelated, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires Windows Developer Mode or elevation")
    with pytest.raises(ValueError):
        contained(repo, "link/private.py")


def test_corrupt_and_forged_metadata_are_ignored(repo):
    service = RunService([repo], AutoDevConfig())
    identifier = next(iter(service.repositories))
    folder = repo / ".autodev/dashboard"
    folder.mkdir(parents=True)
    (folder / ("a" * 12 + ".json")).write_text("[]")
    (folder / ("b" * 12 + ".json")).write_text(
        json.dumps(
            {
                "id": identifier + ":" + "b" * 12,
                "repository_id": "another-project",
                "run_id": "b" * 12,
                "status": "running",
            }
        )
    )
    asyncio.run(service.initialize())
    assert not service.records


def test_workflow_exception_is_safe_and_failed(repo):
    def factory(config, root):
        return SimpleNamespace(
            integration=SimpleNamespace(run_id="c" * 12),
            run_task=AsyncMock(side_effect=RuntimeError("password=synthetic")),
        )

    async def exercise():
        service = RunService([repo], AutoDevConfig(), factory)
        record = await service.start(
            StartRun(
                repository_id=next(iter(service.repositories)), instructions="Implement modules"
            )
        )
        await asyncio.gather(*service.tasks.values())
        assert record["status"] == "failed"
        assert "synthetic" not in json.dumps(record)

    asyncio.run(exercise())


def test_sandbox_cancellation_waits_for_bounded_cleanup():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocking_check():
        entered.set()
        assert release.wait(3)
        finished.set()

    async def exercise():
        task = asyncio.create_task(SandboxChecks._blocking(blocking_check))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished.is_set()

    asyncio.run(exercise())
