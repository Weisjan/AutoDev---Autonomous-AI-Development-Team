import asyncio
import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from project_fakes import ProjectModels, project_repository, workflow  # noqa: E402

from autodev.config import AutoDevConfig  # noqa: E402
from autodev.web.app import create_app  # noqa: E402


def test_project_api_pause_restart_verified_resume_and_report(tmp_path):
    root = project_repository(tmp_path / "repository")
    models = ProjectModels()
    first = True

    def factory(config, repo, run_id=None):
        nonlocal first
        instance = workflow(config, repo, models, run_id=run_id)
        if first:
            # Request pause through the same supported method before execution.
            original = instance.architect.design

            async def design(*args):
                result = await original(*args)
                instance.request_pause()
                return result

            instance.architect.design = design
            first = False
        return instance

    app = create_app([root], project_factory=factory)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 555)) as client:
        client.headers["X-AutoDev-CSRF"] = client.get("/api/session").json()["csrf"]
        project = client.get("/api/projects").json()[0]["id"]
        result = client.post(
            "/api/runs",
            json={
                "repository_id": project,
                "instructions": "Build composed Python project",
                "mode": "project",
            },
        )
        assert result.status_code == 202
        key = result.json()["id"]
        client.portal.call(lambda: asyncio.gather(*app.state.service.tasks.values()))
        paused = client.get(f"/api/runs/{key}").json()
        assert paused["status"] == "paused"
        assert paused["report"]["checkpoint_safe"]
        assert paused["report"]["specification"]["tasks"][2]["depends_on"] == [
            "foundation",
            "utility",
        ]
    restarted = create_app([root], project_factory=factory)
    with TestClient(
        restarted, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 555)
    ) as client:
        client.headers["X-AutoDev-CSRF"] = client.get("/api/session").json()["csrf"]
        assert client.get("/api/runs").json()[0]["status"] == "paused"
        assert client.post(f"/api/runs/{key}/resume", json={}).status_code == 409
        assert client.post(f"/api/runs/{key}/resume", json={"confirmed": True}).status_code == 200
        client.portal.call(lambda: asyncio.gather(*restarted.state.service.tasks.values()))
        result = client.get(f"/api/runs/{key}").json()
        assert result["status"] == "succeeded", result
        assert len(result["report"]["checkpoint_history"]) >= 7
        files = client.get(f"/api/runs/{key}/files").json()
        assert "README.md" in {f["path"] for f in files}
        assert client.get(f"/api/runs/{key}/report").json()["mode"] == "project"
        assert models.calls.count("foundation") == 1


def test_interrupted_project_history_and_invalid_checkpoint_block_resume(tmp_path):
    root = project_repository(tmp_path / "repository")
    models = ProjectModels()
    instance = workflow(AutoDevConfig(), root, models)

    def observe(event):
        if event["stage"] == "developer_started":
            instance.request_pause()

    instance.observer = observe
    report = asyncio.run(instance.run_task("Build a composed project"))
    # Emulate an interrupted process at a persisted safe boundary.
    report.integration_status, report.finished_at = "integrated", ""
    report_file = instance.integration.root / "project_report.json"
    report_file.write_text(report.model_dump_json())
    checkpoint = (
        instance.integration.root
        / "checkpoints"
        / f"{report.checkpoint_history[-1].number:03d}.json"
    )
    checkpoint.write_text(json.dumps({"version": 900}))
    with TestClient(
        create_app([root]), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 555)
    ) as client:
        client.headers["X-AutoDev-CSRF"] = client.get("/api/session").json()["csrf"]
        records = client.get("/api/runs").json()
        assert records[0]["status"] == "interrupted"
        result = client.post(f"/api/runs/{records[0]['id']}/resume", json={"confirmed": True})
        assert result.status_code == 409
        assert not client.app.state.service.tasks
