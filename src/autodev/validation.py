"""Attribution for fixed-format Ruff diagnostics, independent of pytest failures."""

import re

from autodev.schemas import TestRunResult


def lint_failure_paths(result: TestRunResult) -> set[str]:
    # Docker's cwd is /workspace. Do not infer ownership from arbitrary source snippets
    # or the 'Found N errors' footer. Truncated/unknown diagnostics are not repairable.
    if result.timed_out or "output truncated" in result.stdout:
        return set()
    paths = set(
        re.findall(
            r"^(?:/workspace/|\./)?([A-Za-z0-9_./-]+):\d+:\d+: "
            r"(?:[A-Z]+\d+|invalid-syntax)\b",
            result.stdout.replace("\\", "/"),
            re.MULTILINE,
        )
    )
    return paths


def classify_baseline_lint(result: TestRunResult, generated_paths: set[str]) -> None:
    if result.passed or result.infrastructure_failed or result.skipped:
        return
    paths = lint_failure_paths(result)
    if paths - generated_paths:
        result.failure_kind = "baseline"
        result.reason = (
            "Ruff reported files outside integrated task ownership (protected/unowned baseline). "
            "No developer correction can modify these files; manual baseline review is required."
        )
