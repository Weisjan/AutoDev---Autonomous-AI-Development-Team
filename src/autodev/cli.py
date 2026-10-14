from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from autodev.config import AutoDevConfig, load_config_from_env
from autodev.orchestrator import build_orchestrator
from autodev.parallel import build_parallel_orchestrator
from autodev.planning import TaskPlan
from autodev.providers import ProviderError


def main() -> None:
    parser = argparse.ArgumentParser(prog="autodev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run an AutoDev task")
    task_group = run_parser.add_mutually_exclusive_group(required=False)
    task_group.add_argument("--task", help="Task text for the developer agent")
    task_group.add_argument("--task-file", type=Path, help="Path to a task prompt file")
    run_parser.add_argument(
        "--example", choices=["calculator", "parallel-demo"], help="Run a bundled example"
    )
    run_parser.add_argument("--workspace", type=Path, help="Generated workspace directory")
    run_parser.add_argument("--sandbox-backend", choices=["dry_run", "docker"])
    run_parser.add_argument("--max-iterations", type=int)
    run_parser.add_argument("--provider", choices=["codex_cli", "openai_api"])
    run_parser.add_argument("--parallel", action="store_true", help="Use isolated task worktrees")
    run_parser.add_argument("--repo", type=Path, default=Path("."))
    run_parser.add_argument(
        "--plan-file", type=Path, help="Use a validated saved parallel task plan"
    )
    run_parser.add_argument("--concurrency", type=int)
    run_parser.add_argument("--max-tasks", type=int)
    run_parser.add_argument("--max-corrections", type=int)
    run_parser.add_argument("--max-model-calls", type=int)
    run_parser.add_argument("--workflow-timeout", type=int)

    args = parser.parse_args()
    if args.command == "run":
        try:
            asyncio.run(_run(args))
        except ProviderError as exc:
            raise SystemExit(str(exc)) from None


async def _run(args: argparse.Namespace) -> None:
    config = load_config_from_env()
    task = _resolve_task(args)
    seed_tests_dir = _resolve_seed_tests(args)

    updates = {}
    if getattr(args, "provider", None):
        updates["provider"] = args.provider
    if args.workspace:
        updates["workspace_dir"] = args.workspace
    if args.sandbox_backend:
        updates["sandbox"] = config.sandbox.model_dump() | {"backend": args.sandbox_backend}
    if args.max_iterations is not None:
        updates["agents"] = config.agents.model_dump() | {"max_iterations": args.max_iterations}
    parallel_updates = {
        field: getattr(args, option)
        for field, option in (
            ("concurrency", "concurrency"),
            ("max_tasks", "max_tasks"),
            ("max_corrections", "max_corrections"),
            ("max_model_calls", "max_model_calls"),
            ("workflow_timeout_seconds", "workflow_timeout"),
        )
        if getattr(args, option, None) is not None
    }
    if parallel_updates:
        updates["parallel"] = config.parallel.model_dump() | parallel_updates
    if updates:
        config = AutoDevConfig.model_validate(config.model_dump() | updates)

    if getattr(args, "parallel", False):
        if args.workspace or args.max_iterations is not None:
            raise SystemExit("--workspace and --max-iterations apply to sequential runs only")
        plan = None
        if args.plan_file:
            plan = TaskPlan.model_validate_json(args.plan_file.read_text(encoding="utf-8"))
        orchestrator = build_parallel_orchestrator(config, args.repo)
        result = await orchestrator.run_task(task, seed_tests_dir=seed_tests_dir, plan=plan)
    else:
        if getattr(args, "plan_file", None) or parallel_updates or args.example == "parallel-demo":
            raise SystemExit("parallel options and parallel-demo require --parallel")
        orchestrator = build_orchestrator(config)
        result = await orchestrator.run_task(task, seed_tests_dir=seed_tests_dir)
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    if getattr(args, "parallel", False) and not result.succeeded:
        raise SystemExit(1)


def _resolve_task(args: argparse.Namespace) -> str:
    if args.example == "parallel-demo":
        return (Path("examples") / "parallel" / "task.md").read_text(encoding="utf-8")
    if args.example == "calculator":
        return (Path("examples") / "calculator" / "task.md").read_text(encoding="utf-8")
    if args.task_file:
        return args.task_file.read_text(encoding="utf-8")
    if args.task:
        return args.task
    raise SystemExit("Provide --task, --task-file, or --example calculator")


def _resolve_seed_tests(args: argparse.Namespace) -> Path | None:
    if args.example == "parallel-demo":
        return Path("examples") / "parallel" / "tests"
    if args.example == "calculator":
        return Path("examples") / "calculator" / "tests"
    return None
