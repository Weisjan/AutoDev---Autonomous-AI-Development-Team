import re
import runpy
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from autodev.sandbox import DEFAULT_RUFF_COMMAND

ACCEPTANCE = (
    Path(__file__).resolve().parents[1] / "examples/parallel/tests/test_parallel_acceptance.py"
)


def acceptance_functions(monkeypatch, broken=None):
    # Trusted stubs only: never execute generated implementations on the host.
    arithmetic = ModuleType("parallel_arithmetic")
    arithmetic.add = lambda a, b: a + b
    arithmetic.multiply = lambda a, b: a * b
    text = ModuleType("parallel_text")
    text.slugify = lambda value: re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if broken == "slugify":
        text.slugify = lambda _: ""
    elif broken:
        setattr(arithmetic, broken, lambda a, b: 0)
    monkeypatch.setitem(sys.modules, "parallel_arithmetic", arithmetic)
    monkeypatch.setitem(sys.modules, "parallel_text", text)
    namespace = runpy.run_path(str(ACCEPTANCE))
    return [value for name, value in namespace.items() if name.startswith("test_")]


def evaluate(functions):
    for function in functions:
        for marker in function.pytestmark:
            for parameters in marker.args[1]:
                function(*parameters)


def test_parallel_acceptance_tests_accept_both_valid_modules(monkeypatch):
    evaluate(acceptance_functions(monkeypatch))


@pytest.mark.parametrize("broken", ["add", "multiply", "slugify"])
def test_parallel_acceptance_tests_reject_each_broken_implementation(monkeypatch, broken):
    with pytest.raises(AssertionError):
        evaluate(acceptance_functions(monkeypatch, broken))


@pytest.mark.parametrize("modules_present", [False, True])
def test_acceptance_imports_lint_before_and_after_generation(tmp_path, modules_present):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_parallel_acceptance.py").write_text(ACCEPTANCE.read_text())
    if modules_present:
        for name in ("parallel_arithmetic.py", "parallel_text.py"):
            (tmp_path / name).write_text("# Trusted placeholder for static lint discovery.\n")
    completed = subprocess.run(
        [sys.executable, *DEFAULT_RUFF_COMMAND[1:]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
