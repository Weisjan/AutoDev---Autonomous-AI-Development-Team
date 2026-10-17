"""Playwright-only server: real orchestration/Git, explicitly mocked model and checks."""

import tempfile
from pathlib import Path

import uvicorn
from project_fakes import ProjectModels, project_repository
from project_fakes import workflow as project_workflow
from web_fakes import repository, workflow_factory

from autodev.web.app import create_app


def main():
    # Retained by the OS temp policy; never reuse or delete user reports/repositories.
    folder = Path(tempfile.mkdtemp(prefix="autodev-web-smoke-"))
    root = repository(folder / "offline-example")
    project_root = project_repository(folder / "offline-project")
    project_models = ProjectModels()
    project_models.delay = 1.0

    def project_factory(config, repo, run_id=None):
        return project_workflow(config, repo, project_models, run_id=run_id)

    app = create_app(
        [root, project_root], factory=workflow_factory, port=8001, project_factory=project_factory
    )
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False)


if __name__ == "__main__":
    main()
