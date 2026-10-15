"""Playwright-only server: real orchestration/Git, explicitly mocked model and checks."""
import tempfile
from pathlib import Path

import uvicorn
from web_fakes import repository, workflow_factory

from autodev.web.app import create_app


def main():
    # Retained by the OS temp policy; never reuse or delete user reports/repositories.
    folder = Path(tempfile.mkdtemp(prefix="autodev-web-smoke-"))
    root = repository(folder / "offline-example")
    app = create_app([root], factory=workflow_factory, port=8001)
    uvicorn.run(app, host="127.0.0.1", port=8001, access_log=False)


if __name__ == "__main__":
    main()
