from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from autodev.config import AutoDevConfig, load_config_from_env
from autodev.orchestrator import build_orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(prog="autodev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an AutoDev task")
    task_group = run_parser.add_mutually_exclusive_group(required=False)
    task_group.add_argument("--task", help="Task text for the developer agent")
    task_group.add_argument("--task-file", type=Path, help="Path to a task prompt file")
    run_parser.add_argument("--example", choices=["calculator"], help="Run a bundled example")
    run_parser.add_argument("--workspace", type=Path, help="Generated workspace directory")
    run_parser.add_argument("--sandbox-backend", choices=["dry_run", "docker"])
    run_parser.add_argument("--max-iterations", type=int)

    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(_run(args))


async def _run(args: argparse.Namespace) -> None:
    config = load_config_from_env()
    task = _resolve_task(args)
    seed_tests_dir = _resolve_seed_tests(args)

    updates = {}
    if args.workspace:
        updates["workspace_dir"] = args.workspace
    if args.sandbox_backend:
        updates["sandbox"] = config.sandbox.model_dump() | {"backend": args.sandbox_backend}
    if args.max_iterations is not None:
        updates["agents"] = config.agents.model_dump() | {"max_iterations": args.max_iterations}
    if updates:
        config = AutoDevConfig.model_validate(config.model_dump() | updates)

    orchestrator = build_orchestrator(config)
    result = await orchestrator.run_task(task, seed_tests_dir=seed_tests_dir)
    print(json.dumps(result.model_dump(mode="json"), indent=2))


def _resolve_task(args: argparse.Namespace) -> str:
    if args.example == "calculator":
        return (Path("examples") / "calculator" / "task.md").read_text(encoding="utf-8")
    if args.task_file:
        return args.task_file.read_text(encoding="utf-8")
    if args.task:
        return args.task
    raise SystemExit("Provide --task, --task-file, or --example calculator")


def _resolve_seed_tests(args: argparse.Namespace) -> Path | None:
    if args.example == "calculator":
        return Path("examples") / "calculator" / "tests"
    return None
