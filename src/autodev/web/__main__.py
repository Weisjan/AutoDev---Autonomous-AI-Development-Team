from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from autodev.config import load_config_from_env
from autodev.web.app import create_app


def main():
    parser = argparse.ArgumentParser(description="AutoDev localhost dashboard API")
    parser.add_argument("--repo", type=Path, action="append", help="Allowlisted Git repository")
    parser.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    app = create_app(args.repo, load_config_from_env(), port=args.port)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        access_log=False,
        timeout_graceful_shutdown=75,
    )


if __name__ == "__main__":
    main()
