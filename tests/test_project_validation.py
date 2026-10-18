"""Invoice regressions: real temporary Git, offline models/checks, real static Ruff."""

import asyncio
import subprocess
import sys
from pathlib import Path
from time import monotonic
from unittest.mock import AsyncMock

import pytest
from project_fakes import git, specification, workflow
from test_providers import FakeProcess, install_process
from web_fakes import repository

from autodev.architect import ProjectArchitect, milestone_requirements
from autodev.config import AutoDevConfig, CodexCLIConfig
from autodev.parallel import SandboxChecks
from autodev.project_models import ProjectSpec
from autodev.providers import CodexCLIProvider, ProviderSchemaError
from autodev.sandbox import DockerSandbox, ruff_command
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult
from autodev.schemas import TestRunResult as CheckResult
from autodev.validation import classify_baseline_lint, lint_failure_paths

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/project"
REQUEST = (EXAMPLE / "task.md").read_text(encoding="utf-8")
CONTENTS = {
    "domain.py": (
        "def subtotal(prices):\n"
        "    if any(price < 0 for price in prices):\n"
        '        raise ValueError("negative price")\n'
        "    return sum(prices)\n"
    ),
    "formatting.py": 'def format_total(cents):\n    return f"${cents // 100}.{cents % 100:02d}"\n',
    "app.py": (
        "from domain import subtotal\nfrom formatting import format_total\n\n\n"
        "def invoice_total(prices):\n    return format_total(subtotal(prices))\n"
    ),
    "README.md": "# Invoice\nDomain, formatting, application and trusted tests.\n",
}


def invoice_spec():
    data = specification().model_dump()
    replacements = {
        "base.py": "domain.py",
        "utility.py": "formatting.py",
        "tests/test_base.py": "tests/test_domain.py",
        "tests/test_utility.py": "tests/test_formatting.py",
    }
    data["repository_structure"] = [replacements.get(p, p) for p in data["repository_structure"]]
    for component in data["components"]:
        component["files"] = [replacements.get(p, p) for p in component["files"]]
    for task in data["tasks"]:
        task["owned_files"] = [replacements.get(p, p) for p in task["owned_files"]]
        task["test_paths"] = [replacements.get(p, p) for p in task["test_paths"]]
    data["tasks"][2]["owned_files"] = ["app.py"]
    for milestone in data["milestones"]:
        milestone["test_paths"] = [replacements.get(p, p) for p in milestone["test_paths"]]
    return ProjectSpec.model_validate(data)


class InvoiceModels:
    def __init__(self, plan=None):
        self.plan = plan or invoice_spec()
        self.calls, self.events = [], []
        self.barrier = asyncio.Event()
        self.entered = 0

    def client(self, path):
        controller = self

        class Client:
            async def architect(self, request, files, max_tasks):
                return controller.plan

            async def generate_code(self, prompt, context, feedback):
                task = next(t for t in controller.plan.tasks if t.id == path.name)
                controller.calls.append(task.id)
                controller.events.append(("start", task.id, monotonic()))
                if len(controller.plan.tasks) > 1 and task.id in {"foundation", "utility"}:
                    controller.entered += 1
                    if controller.entered >= 2:
                        controller.barrier.set()
                    await asyncio.wait_for(controller.barrier.wait(), 3)
                    await asyncio.sleep(0.03)
                required = (
                    ("domain.py", "formatting.py")
                    if task.id == "application"
                    else (("app.py",) if task.id == "documentation" else ())
                )
                for name in required:
                    assert (path / name).read_text() == CONTENTS[name]
                    assert any(f.path == name and f.content == CONTENTS[name] for f in context)
                controller.events.append(("end", task.id, monotonic()))
                return CodeGenerationResult(
                    summary="Offline invoice fixture",
                    files=[GeneratedFile(path=p, content=CONTENTS[p]) for p in task.owned_files],
                )

            async def review(self, task, files, test_result):
                return ReviewResult(approved=True, risk_level="low", summary="Offline fixture")

        return Client()


class FixtureSandbox:
    """No Docker/model network needed; static Ruff does not execute fixture source."""

    def __init__(self):
        self.pytest_calls, self.lint_calls = [], []
        self.injected_lint = None
        self.lint_failures = 0

    def check_environment(self, *args):
        return CheckResult(command=["mock-environment"], exit_code=0)

    def run_pytest(self, workspace, command, *args):
        paths = [p for p in command if p.startswith("tests/")]
        modules = (
            [Path(p).stem.removeprefix("test_") + ".py" for p in paths]
            if paths
            else (["domain.py", "formatting.py", "app.py"])
        )
        for name in modules:
            assert (workspace / name).read_text() == CONTENTS[name]
        self.pytest_calls.append((paths, monotonic()))
        return CheckResult(command=list(command), exit_code=0, stdout="2 passed (mocked pytest)\n")

    def run_ruff(self, workspace, timeout, maximum, paths=None):
        self.lint_calls.append(paths)
        command = ruff_command(paths)
        if self.lint_failures:
            self.lint_failures -= 1
            return CheckResult(command=command, exit_code=1, stdout=self.injected_lint)
        result = subprocess.run(
            [sys.executable, *command[1:]],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CheckResult(
            command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr
        )


@pytest.fixture
def invoice_repo(tmp_path):
    root = repository(tmp_path / "invoice")
    (root / "tests").mkdir()
    for source in (EXAMPLE / "tests").glob("*.py"):
        (root / "tests" / source.name).write_bytes(source.read_bytes())
    git(root, "add", "tests")
    git(root, "commit", "-m", "Trusted invoice fixture tests")
    return root


def checked_workflow(repo, models):
    checks = SandboxChecks(AutoDevConfig())
    sandbox = FixtureSandbox()
    checks.sandbox = sandbox
    return workflow(AutoDevConfig(), repo, models, checks), sandbox


def test_successful_domain_pytest_and_preexisting_protected_i001_do_not_retry(invoice_repo):
    data = invoice_spec().model_dump()
    data["tasks"] = data["tasks"][:1]
    data["milestones"] = data["milestones"][:1]
    data["milestones"][0].update(task_ids=["foundation"], test_paths=["tests/test_domain.py"])
    models = InvoiceModels(ProjectSpec.model_validate(data))
    instance, sandbox = checked_workflow(invoice_repo, models)
    # A static baseline lint probe reproduces the real protected-test I001 once domain exists.
    before = (invoice_repo / "tests/test_domain.py").read_bytes()

    def pause_after_domain(event):
        if event["stage"] == "checks_finished":
            instance.request_pause()

    instance.observer = pause_after_domain
    report = asyncio.run(instance.run_task("Implement invoice domain only"))
    assert report.integration_status == "paused", report.stopped_reason
    full_lint = sandbox.run_ruff(instance.integration.integration.path, 30, 10000)
    assert full_lint.exit_code == 1
    assert "tests/test_domain.py:1:1: I001" in full_lint.stdout.replace("\\", "/")
    assert "2 passed" in report.rounds[0].checks.pytest.stdout
    assert report.rounds[0].checks.ruff.passed
    assert "baseline" in report.rounds[0].checks.ruff.reason
    assert models.calls == ["foundation"]
    assert all(not r.correction_tasks for r in report.rounds)
    assert (invoice_repo / "tests/test_domain.py").read_bytes() == before
    integration = instance.integration.integration.path
    # Git can materialize CRLF on Windows; the protected tracked blob must be identical.
    assert git(invoice_repo, "rev-parse", "HEAD:tests/test_domain.py") == git(
        integration, "rev-parse", "HEAD:tests/test_domain.py"
    )
    assert git(integration, "diff", "--name-only", "HEAD", "--", "tests") == ""


def test_invoice_three_stages_overlap_and_wait_for_validated_integration(invoice_repo):
    models = InvoiceModels()
    instance, sandbox = checked_workflow(invoice_repo, models)
    validated = []

    def observe(event):
        if event["stage"] == "checks_finished":
            assert instance.current_report.rounds[-1].checks.passed
            validated.append(monotonic())

    instance.observer = observe
    original = git(invoice_repo, "rev-parse", "HEAD")
    report = asyncio.run(instance.run_task(REQUEST))
    assert report.succeeded, report.stopped_reason
    assert [m.id for m in report.milestones] == ["core", "application", "documentation"]
    assert [len(m.task_ids) for m in report.specification.milestones] == [2, 1, 1]
    starts = [
        t
        for event, task, t in models.events
        if event == "start" and task in {"foundation", "utility"}
    ]
    ends = [
        t
        for event, task, t in models.events
        if event == "end" and task in {"foundation", "utility"}
    ]
    assert max(starts) < min(ends)
    application_start = next(
        t for event, task, t in models.events if (event, task) == ("start", "application")
    )
    assert application_start > validated[0] > max(ends)
    documentation_start = next(
        t for event, task, t in models.events if (event, task) == ("start", "documentation")
    )
    assert documentation_start > validated[1]
    tasks = {t.task.id: t for t in report.tasks}
    assert tasks["application"].base_commit == report.milestones[0].commit
    assert tasks["documentation"].base_commit == report.milestones[1].commit
    assert sandbox.pytest_calls[-1][0] == []  # Full suite at final validation.
    assert sandbox.lint_calls == [
        ["domain.py", "formatting.py"],
        *[["app.py", "domain.py", "formatting.py"] for _ in range(3)],
    ]
    assert len({t.worktree for t in report.tasks}) == 4
    assert git(invoice_repo, "rev-parse", "HEAD") == original
    assert len(report.checkpoint_history) == 8
    assert report.model_calls_reserved == 6  # Architect, four developers, reviewer.


@pytest.mark.parametrize(
    "diagnostic, status, corrected",
    [
        (
            "tests/test_domain.py:1:1: I001 Import block is un-sorted or un-formatted\n",
            "baseline_failed",
            False,
        ),
        ("legacy.py:2:1: F821 Undefined name\n", "baseline_failed", False),
        ("incomplete output", "checks_failed", False),
        ("domain.py:1:1: I001 Import block is un-sorted or un-formatted\n", "reviewed", True),
    ],
)
def test_lint_attribution_never_falls_back_to_all_batch_owners(
    invoice_repo, diagnostic, status, corrected
):
    models = InvoiceModels()
    instance, sandbox = checked_workflow(invoice_repo, models)
    sandbox.injected_lint, sandbox.lint_failures = diagnostic, 1
    report = asyncio.run(instance.run_task(REQUEST))
    assert report.integration_status == status, report.stopped_reason
    assert models.calls.count("utility") == 1
    assert models.calls.count("foundation") == (2 if corrected else 1)
    assert report.rounds[0].correction_tasks == (["foundation"] if corrected else [])
    if status == "baseline_failed":
        assert report.rounds[0].checks.ruff.failure_kind == "baseline"
        assert "no developer corrections" in report.stopped_reason
        assert not report.checkpoint_safe
        assert "application" not in models.calls


@pytest.mark.parametrize("mutation", ["four", "grouping", "dependent", "renamed"])
def test_architect_rejects_serialized_or_regrouped_invoice_plan(mutation):
    data = invoice_spec().model_dump()
    if mutation == "four":
        first = data["milestones"][0]
        first["task_ids"] = ["foundation"]
        data["milestones"].insert(1, first | {"id": "formatting", "task_ids": ["utility"]})
    elif mutation == "grouping":
        data["milestones"][0]["task_ids"] = ["foundation"]
        data["milestones"][1]["task_ids"].insert(0, "utility")
    elif mutation == "dependent":
        data["tasks"][1]["depends_on"] = ["foundation"]
    else:
        data["milestones"][0].update(id="wrong", description="wrong")
    client = AsyncMock()
    client.architect.return_value = ProjectSpec.model_validate(data)
    files = [
        GeneratedFile(path=f"tests/test_{name}.py", content="trusted")
        for name in ("domain", "formatting", "app")
    ]
    with pytest.raises(ProviderSchemaError, match="Architecture"):
        asyncio.run(ProjectArchitect(client).design(REQUEST, files))
    client.architect.assert_awaited_once()


def test_architect_cli_prompt_preserves_explicit_three_stage_contract(monkeypatch):
    spec = invoice_spec()
    _, processes = install_process(
        monkeypatch, lambda: FakeProcess(spec.model_dump_json().encode())
    )
    asyncio.run(CodexCLIProvider(CodexCLIConfig()).architect(REQUEST, [], 4))
    prompt = processes[0].stdin.write.call_args.args[0].decode()
    assert "exactly 3 ordered milestones as requested" in prompt
    assert "tasks and four ordered milestones" not in prompt
    assert "no artificial dependencies" in prompt


@pytest.mark.parametrize(
    "instructions, expected",
    [
        ("Build project", None),
        ("Design three milestones", 3),
        ("Use 2 milestones", 2),
    ],
)
def test_explicit_milestone_count_detection(instructions, expected):
    assert milestone_requirements(instructions)[0] == expected


@pytest.mark.parametrize(
    "instructions",
    ["Design 5 milestones", "Use 0 milestones", "Use 2 milestones, exactly 3 milestones"],
)
def test_unsupported_or_conflicting_counts_stop_before_model_call(instructions):
    client = AsyncMock()
    with pytest.raises(ProviderSchemaError):
        asyncio.run(ProjectArchitect(client).design(instructions, []))
    client.architect.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    ["../bad.py", "tests/test_domain.py", "--fix", "domain.py;whoami", ".env", "domain.py::thing"],
)
def test_scoped_lint_paths_are_validated_before_sandbox_execution(path):
    checks = SandboxChecks(AutoDevConfig())
    checks._blocking = AsyncMock()
    with pytest.raises(ValueError):
        asyncio.run(checks.run(Path.cwd(), lint_paths=[path]))
    checks._blocking.assert_not_awaited()


def test_scoped_ruff_keeps_docker_restrictions_and_all_strict_rules(tmp_path, monkeypatch):
    calls = []

    def run(command, *args):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", ""), False

    monkeypatch.setattr("autodev.sandbox._run_bounded", run)
    result = DockerSandbox("test-image").run_ruff(tmp_path, 30, 1000, ["domain.py"])
    assert result.passed
    command = calls[0]
    assert command[-2:] == ["--", "domain.py"]
    for flag, value in [
        ("--network", "none"),
        ("--user", "65534:65534"),
        ("--memory", "256m"),
        ("--cpus", "1"),
        ("--pids-limit", "128"),
        ("--select", "E,F,I,UP,B,SIM"),
    ]:
        assert command[command.index(flag) + 1] == value
    assert "--read-only" in command and "--isolated" in command
    assert "--fix" not in command


def test_infrastructure_and_truncated_lint_are_not_reclassified_as_baseline():
    result = CheckResult(
        command=["ruff"],
        exit_code=125,
        failure_kind="infrastructure",
        stdout="tests/test_domain.py:1:1: I001 import block\n",
    )
    classify_baseline_lint(result, {"domain.py"})
    assert result.infrastructure_failed and not result.baseline_failed
    result.failure_kind = "code"
    result.stdout += "... output truncated ..."
    assert not lint_failure_paths(result)


def test_documentation_only_lint_scope_does_not_scan_the_baseline(tmp_path):
    checks = SandboxChecks(AutoDevConfig())
    checks._blocking = AsyncMock(return_value=CheckResult(command=["mock"], exit_code=0))
    result = asyncio.run(checks.run(tmp_path, lint_paths=[]))
    assert result.passed
    assert checks._blocking.await_count == 2  # environment and complete pytest, no Ruff process.
    assert "no Ruff process" in result.ruff.reason
