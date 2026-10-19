import asyncio

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402
from web_fakes import repository, workflow_factory  # noqa: E402

from autodev.config import AgentConfig, AutoDevConfig  # noqa: E402
from autodev.web.app import create_app  # noqa: E402


@pytest.mark.parametrize("explicit", [False, True])
def test_model_policy_api_freezes_roles_and_preserves_legacy_defaults(tmp_path, explicit):
    root = repository(tmp_path / "repository")
    captured = []

    def factory(config, repo):
        captured.append(config)
        return workflow_factory(config, repo)

    config = AutoDevConfig(
        agents=AgentConfig(developer_model="legacy-developer", reviewer_model="legacy-reviewer")
    )
    app = create_app([root], config=config, factory=factory)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 123)) as client:
        client.headers["X-AutoDev-CSRF"] = client.get("/api/session").json()["csrf"]
        options = client.get("/api/settings").json()["model_options"]
        assert options["default_dashboard_preset"] == "balanced"
        assert "unverified" in options["availability"]
        assert "ultra" not in options["reasoning_efforts"]
        body = {
            "repository_id": client.get("/api/projects").json()[0]["id"],
            "instructions": "Build two offline modules",
        }
        if explicit:
            body["model_policy"] = {
                "preset": "balanced",
                "overrides": {"reviewer": {"reasoning_effort": "xhigh"}},
            }
        response = client.post("/api/runs", json=body)
        assert response.status_code == 202, response.text
        key = response.json()["id"]
        client.portal.call(lambda: asyncio.gather(*app.state.service.tasks.values()))
        result = client.get(f"/api/runs/{key}").json()
        assert result["status"] == "succeeded", result
        policy = result["report"]["model_policy"]
        assert policy["kind"] == "resolved" and policy["version"] == 1
        assert captured[0].parallel == config.parallel
        if explicit:
            assert policy["architect"]["model"] == "gpt-6-astra"
            assert policy["developer"]["model"] == "gpt-6.1-sol"
            assert policy["reviewer"]["reasoning_effort"] == "xhigh"
        else:
            assert policy["preset"] is None
            assert (
                policy["architect"]["model"] == policy["developer"]["model"] == "legacy-developer"
            )
            assert policy["reviewer"]["model"] == "legacy-reviewer"
            assert policy["reviewer"]["reasoning_effort"] is None
        assert "model_policy" not in captured[0].parallel.model_dump()
        assert config.model_policy is None  # No global mutable settings were changed.
        assert (
            client.post(
                f"/api/runs/{key}/resume",
                json={"confirmed": True, "model_policy": {"preset": "fast"}},
            ).status_code
            == 422
        )


@pytest.mark.parametrize(
    "bad",
    [
        {"preset": "unknown"},
        {"preset": "balanced", "overrides": {"architect": {"model": "unknown"}}},
        {"preset": "balanced", "overrides": {"developer": {"reasoning_effort": "ultra"}}},
        {"preset": "balanced", "overrides": {"developer": {"executable": "bad"}}},
        {"kind": "resolved", "preset": "balanced"},
    ],
)
def test_invalid_model_policy_api_is_422_before_workflow_or_storage(tmp_path, bad):
    root = repository(tmp_path / "repository")
    app = create_app(
        [root], factory=lambda *args: pytest.fail("Workflow created for invalid policy")
    )
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 123)) as client:
        client.headers["X-AutoDev-CSRF"] = client.get("/api/session").json()["csrf"]
        project = client.get("/api/projects").json()[0]["id"]
        result = client.post(
            "/api/runs",
            json={
                "repository_id": project,
                "instructions": "Build offline modules",
                "model_policy": bad,
            },
        )
        assert result.status_code == 422
        assert result.json()["error_kind"] == "configuration_invalid"
        assert not app.state.service.tasks
        assert not (root / ".autodev").exists()
