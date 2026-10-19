import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from project_fakes import ProjectModels, git, project_repository, workflow
from test_project import paused

from autodev.checkpoints import RecoveryRequired, configuration_digest
from autodev.config import AutoDevConfig
from autodev.model_policy import PRESETS, ModelPolicy, resolve_config
from autodev.project_models import ProjectReport


def old_hash(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def make_v04_checkpoint(instance, report, config):
    """Write the pre-v0.5 serialization in a disposable repository only."""
    data = report.model_dump(mode="json")
    for key in ("report_version", "model_policy", "error_kind"):
        data.pop(key)
    attempts = [data["planner_execution"], data["reviewer_execution"]]
    attempts += [a for t in data["tasks"] for a in t["attempts"]]
    for attempt in filter(None, attempts):
        attempt.pop("error_kind")
        attempt.pop("execution")
    original_config = config.model_dump(mode="json")
    original_config.pop("model_policy")
    original_config.pop("model_overrides")
    data["configuration_digest"] = old_hash(original_config)
    data["checkpoint_digest"] = ""
    heads = {t.task.id: git(Path(t.worktree), "rev-parse", "HEAD") for t in report.tasks}
    payload = {"version": 1, "report": data, "task_heads": heads}
    checksum = old_hash(payload)
    file = instance.integration.root / "checkpoints" / f"{len(report.checkpoint_history):03d}.json"
    file.write_text(json.dumps(payload | {"checksum": checksum}), encoding="utf-8")
    live = ProjectReport.model_validate(data | {"checkpoint_digest": checksum})
    return live, file


def test_v04_checksum_and_real_git_resume_preserve_completed_work(tmp_path):
    repo = project_repository(tmp_path / "repository")
    old, report, models = paused(repo)
    live, file = make_v04_checkpoint(old, report, AutoDevConfig())
    before = file.read_bytes()
    runner = workflow(AutoDevConfig(), repo, models, run_id=report.run_id)
    resumed = asyncio.run(runner.run_task(report.request, resume=live))
    assert resumed.succeeded, resumed.stopped_reason
    assert models.calls.count("foundation") == models.calls.count("utility") == 1
    assert file.read_bytes() == before  # Original checkpoint remains immutable.
    assert resumed.report_version == 1 and resumed.model_policy is None


def test_v04_tampering_and_new_policy_cannot_bypass_checksum(tmp_path):
    repo = project_repository(tmp_path / "repository")
    old, report, _ = paused(repo)
    live, file = make_v04_checkpoint(old, report, AutoDevConfig())
    with pytest.raises(RecoveryRequired, match="legacy"):
        asyncio.run(old.store.restore(live, AutoDevConfig(model_policy=ModelPolicy())))
    raw = json.loads(file.read_text())
    raw["report"]["request"] = "tampered"
    file.write_text(json.dumps(raw))
    with pytest.raises(RecoveryRequired, match="checksum"):
        old.store.load(len(live.checkpoint_history))


def test_frozen_policy_resume_does_not_use_changed_preset_defaults(tmp_path, monkeypatch):
    repo = project_repository(tmp_path / "repository")
    config = AutoDevConfig(model_policy=ModelPolicy())
    models = ProjectModels()
    runner = workflow(config, repo, models)
    runner.observer = lambda event: (
        runner.request_pause() if event["stage"] == "developer_started" else None
    )
    report = asyncio.run(runner.run_task("Build composed project"))
    assert report.integration_status == "paused"
    saved = report.model_policy
    assert (
        report.report_version == 2
        and runner.store.load(len(report.checkpoint_history)).version == 2
    )
    monkeypatch.setitem(PRESETS, "balanced", ())
    resumed_config = AutoDevConfig(model_policy=saved)
    assert resolve_config(resumed_config) == saved
    assert configuration_digest(
        config.model_copy(update={"model_policy": saved})
    ) == configuration_digest(resumed_config)
    resumed = asyncio.run(
        workflow(resumed_config, repo, models, run_id=report.run_id).run_task(
            report.request, resume=report
        )
    )
    assert resumed.succeeded and resumed.model_policy == saved


def test_saved_policy_change_is_a_recovery_error(tmp_path):
    repo = project_repository(tmp_path / "repository")
    old, report, _ = paused(repo)
    changed = report.model_copy(
        update={"model_policy": resolve_config(AutoDevConfig(model_policy=ModelPolicy()))}
    )
    with pytest.raises(RecoveryRequired):
        asyncio.run(old.store.restore(changed, AutoDevConfig()))
