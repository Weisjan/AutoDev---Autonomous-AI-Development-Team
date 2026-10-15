from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path

from autodev.config import AutoDevConfig
from autodev.integration import GitOperationError, IntegrationManager
from autodev.parallel import build_parallel_orchestrator, timestamp
from autodev.parallel_schemas import ParallelWorkflowReport
from autodev.planning import TaskPlan
from autodev.web.models import StartRun
from autodev.web.security import contained, redact

ACTIVE = {"running", "cancelling"}
RUN_ID = re.compile(r"^[0-9a-f]{12}$")


def public_report(report: ParallelWorkflowReport) -> dict:
    data = report.model_dump(mode="json")
    # Pydantic properties aren't serialized by v0.2 reports; expose measured outcomes.
    for round_data, round_model in zip(data["rounds"], report.rounds, strict=True):
        if round_model.checks:
            for name in ("pytest", "ruff", "environment"):
                check = getattr(round_model.checks, name)
                if check:
                    round_data["checks"][name]["passed"] = check.passed
    return redact(data)


class RunService:
    def __init__(self, repositories: list[Path], config: AutoDevConfig, factory=None):
        self.repositories = {}
        for supplied in repositories:
            root = supplied.resolve(strict=True)
            if (
                root == Path(root.anchor)
                or str(root).startswith(("\\\\", "//"))
                or ".autodev" in root.parts
                or not (root / ".git").exists()
            ):
                raise ValueError("Register an existing local Git repository root")
            identifier = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest()[:12]
            self.repositories[identifier] = root
        if not self.repositories:
            raise ValueError("At least one repository must be registered")
        self.config = config
        self.factory = factory or build_parallel_orchestrator
        self.records: dict[str, dict] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.revision = 0
        self.lock = asyncio.Lock()

    async def initialize(self):
        for repository_id, root in self.repositories.items():
            try:
                base = contained(root, ".autodev/runs")
                paths = sorted(base.glob("*/report.json"))[-200:]
            except ValueError:
                continue
            for path in paths:
                if not RUN_ID.fullmatch(path.parent.name):
                    continue
                try:
                    safe = contained(root, path.relative_to(root).as_posix())
                    if safe.stat().st_size > 2_000_000:
                        continue
                    report = ParallelWorkflowReport.model_validate_json(safe.read_bytes())
                    if report.run_id != path.parent.name:
                        continue
                    key = repository_id + ":" + report.run_id
                    self.records[key] = self.record(repository_id, report)
                except (OSError, ValueError):
                    continue
            try:
                saved = contained(root, ".autodev/dashboard").glob("*.json")
                for path in sorted(saved)[-200:]:
                    try:
                        self.load_saved(root, repository_id, path)
                    except (OSError, ValueError, TypeError, KeyError, AttributeError):
                        continue
            except (OSError, ValueError):
                continue

    def load_saved(self, root, repository_id, path):
        safe = contained(root, path.relative_to(root).as_posix())
        if safe.stat().st_size > 2_000_000:
            return
        record = json.loads(safe.read_text(encoding="utf-8"))
        key = repository_id + ":" + path.stem
        if (
            not RUN_ID.fullmatch(path.stem)
            or record.get("id") != key
            or record.get("run_id") != path.stem
            or record.get("repository_id") != repository_id
        ):
            return
        for name in ("started_at", "instructions", "stage", "status"):
            if not isinstance(record.get(name), str):
                return
        if record.get("report"):
            data = record["report"]
            for round_data in data.get("rounds", []):
                for check in (round_data.get("checks") or {}).values():
                    if check:
                        check.pop("passed", None)
            validated = ParallelWorkflowReport.model_validate(data)
            if validated.run_id != path.stem:
                return
            record["report"] = public_report(validated)
        if record["status"] in ACTIVE:
            record.update(status="interrupted", stage="interrupted")
        elif record["status"] not in {"succeeded", "failed", "interrupted", "cancelled"}:
            return
        events = record.get("events", [])
        if not isinstance(events, list) or any(
            not isinstance(e, dict)
            or not isinstance(e.get("stage"), str)
            or not isinstance(e.get("at"), str)
            for e in events
        ):
            return
        record["events"] = events[-300:]
        if key in self.records:
            # The canonical report controls the outcome; preserve the dashboard's event log.
            self.records[key]["events"] = redact(record["events"])
        else:
            self.records[key] = redact(
                {
                    name: record[name]
                    for name in (
                        "id",
                        "run_id",
                        "repository_id",
                        "instructions",
                        "status",
                        "stage",
                        "started_at",
                        "report",
                        "events",
                    )
                }
                | {
                    "finished_at": record.get("finished_at", ""),
                    "error": str(record.get("error", "")),
                }
            )

    def record(self, repository_id: str, report: ParallelWorkflowReport) -> dict:
        status = "succeeded" if report.succeeded else "failed"
        if report.integration_status in {"pending", "integrated"} or not report.finished_at:
            status = "interrupted"
        if report.integration_status == "cancelled":
            status = "cancelled"
        return redact(
            {
                "id": repository_id + ":" + report.run_id,
                "run_id": report.run_id,
                "repository_id": repository_id,
                "instructions": report.request,
                "status": status,
                "stage": report.integration_status,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "report": public_report(report),
                "events": [],
            }
        )

    def persist(self, record):
        root = self.repositories[record["repository_id"]]
        directory = contained(root, ".autodev/dashboard")
        directory.mkdir(parents=True, exist_ok=True)
        destination = contained(root, f".autodev/dashboard/{record['run_id']}.json")
        temporary = contained(root, f".autodev/dashboard/{record['run_id']}.tmp")
        temporary.write_text(json.dumps(redact(record)), encoding="utf-8")
        temporary.replace(destination)

    async def projects(self):
        result = []
        for identifier, root in self.repositories.items():
            manager = IntegrationManager(root)
            try:
                branch = await manager.git(root, "branch", "--show-current")
                dirty = bool(
                    await manager.git(root, "status", "--porcelain", "--untracked-files=no")
                )
                error = None
            except GitOperationError:
                branch, dirty, error = "unknown", True, "Git status unavailable"
            result.append(
                {
                    "id": identifier,
                    "name": root.name,
                    "path": str(root),
                    "branch": branch,
                    "dirty": dirty,
                    "error": error,
                }
            )
        return result

    async def start(self, request: StartRun):
        async with self.lock:
            if any(record["status"] in ACTIVE for record in self.records.values()):
                raise RuntimeError(
                    "A workflow is already active; wait for cleanup before starting another"
                )
            root = self.repositories.get(request.repository_id)
            if root is None:
                raise KeyError("Unknown registered repository")
            config = AutoDevConfig.model_validate(
                self.config.model_dump()
                | {
                    "provider": "codex_cli",
                    "sandbox": self.config.sandbox.model_dump() | {"backend": "docker"},
                    "parallel": self.config.parallel.model_dump()
                    | request.model_dump(
                        exclude={
                            "repository_id",
                            "instructions",
                            "example",
                        }
                    ),
                }
            )
            workflow = self.factory(config, root)
            run_id = workflow.integration.run_id
            if not RUN_ID.fullmatch(run_id):
                raise ValueError("Invalid workflow run ID")
            key = request.repository_id + ":" + run_id
            record = {
                "id": key,
                "run_id": run_id,
                "repository_id": request.repository_id,
                "instructions": redact(request.instructions),
                "status": "running",
                "stage": "preparing",
                "started_at": timestamp(),
                "finished_at": "",
                "report": None,
                "events": [],
            }
            # Check storage before launching any model/Git work.
            self.persist(record)
            self.records[key] = record

            def observe(event):
                record["stage"] = event["stage"]
                record["report"] = public_report(
                    ParallelWorkflowReport.model_validate(event["report"])
                )
                record["events"] = (
                    record["events"]
                    + [redact({name: value for name, value in event.items() if name != "report"})]
                )[-300:]
                self.persist(record)
                self.revision += 1

            workflow.observer = observe
            self.tasks[key] = asyncio.create_task(self.execute(workflow, request, record))
            self.tasks[key].add_done_callback(lambda task: self.finalize_cancelled(task, record))
            self.revision += 1
            return record

    def finalize_cancelled(self, task, record):
        # A task cancelled before its coroutine starts cannot run its own finally block.
        if task.cancelled() and record["status"] in ACTIVE:
            record.update(status="cancelled", stage="cancelled", finished_at=timestamp())
            self.persist(record)
            self.revision += 1

    async def execute(self, workflow, request, record):
        try:
            seed, plan = None, None
            if request.example:
                bundled = Path(__file__).resolve().parents[3] / "examples/parallel"
                # Only trusted bundled fixtures, never a browser-supplied file path.
                plan = TaskPlan.model_validate_json((bundled / "plan.json").read_bytes())
                seed = bundled / "tests"
            report = await workflow.run_task(request.instructions, seed_tests_dir=seed, plan=plan)
            record["report"] = public_report(report)
            record["status"] = "succeeded" if report.succeeded else "failed"
        except asyncio.CancelledError:
            record["status"] = "cancelled"
        except Exception:
            record["status"] = "failed"
            record["error"] = "Workflow failed; inspect the retained report and environment"
        finally:
            record["finished_at"] = timestamp()
            if record["status"] == "cancelling":
                record["status"] = "cancelled"
            record["stage"] = record["status"]
            self.persist(record)
            self.revision += 1

    async def cancel(self, key):
        record = self.records[key]
        task = self.tasks.get(key)
        if record["status"] == "running" and task and not task.done():
            record["status"] = "cancelling"
            self.persist(record)
            task.cancel()
            self.revision += 1
        return record

    async def shutdown(self):
        for key, task in self.tasks.items():
            if not task.done() and self.records[key]["status"] != "cancelling":
                await self.cancel(key)
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)

    def files(self, key):
        record = self.records[key]
        report = record.get("report") or {}
        paths = {
            path
            for task in (report.get("plan") or {}).get("tasks", [])
            for path in task["owned_files"]
        }
        result = []
        for path in sorted(paths):
            try:
                file = self.file_path(record, path)
                if file.is_file() and file.stat().st_size <= 256_000:
                    result.append(
                        {"id": hashlib.sha256(path.encode()).hexdigest()[:16], "path": path}
                    )
            except (ValueError, OSError):
                continue
        return result

    def file_path(self, record, path):
        from autodev.planning import owned_path

        owned_path(path)
        if not RUN_ID.fullmatch(record["run_id"]):
            raise ValueError("Invalid run ID")
        root = self.repositories[record["repository_id"]]
        tree = contained(root, f".autodev/runs/{record['run_id']}/integration")
        return contained(tree, path)

    def read_file(self, key, identifier):
        entry = next((file for file in self.files(key) if file["id"] == identifier), None)
        if not entry:
            raise KeyError("Unknown generated file")
        file = self.file_path(self.records[key], entry["path"])
        if file.stat().st_size > 256_000:
            raise ValueError("File is too large to display")
        return redact(file.read_text(encoding="utf-8"))
