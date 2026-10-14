from __future__ import annotations

from typing import Protocol

from autodev.budget import ApiBudgetTracker
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult, TestRunResult


class DeveloperModelClient(Protocol):
    async def generate_code(
        self,
        task: str,
        previous_files: list[GeneratedFile],
        test_output: str | None,
    ) -> CodeGenerationResult:
        """Return generated source files for the current attempt."""
        raise NotImplementedError


class ReviewerModelClient(Protocol):
    async def review(
        self,
        task: str,
        files: list[GeneratedFile],
        test_result: TestRunResult | None,
    ) -> ReviewResult:
        """Return structured review feedback for the final implementation."""
        raise NotImplementedError


class DeveloperAgent:
    def __init__(self, client: DeveloperModelClient, budget: ApiBudgetTracker) -> None:
        self._client = client
        self._budget = budget

    async def generate(
        self,
        task: str,
        previous_files: list[GeneratedFile],
        test_output: str | None,
    ) -> CodeGenerationResult:
        self._budget.reserve_call("developer generation")
        return await self._client.generate_code(task, previous_files, test_output)


class ReviewerAgent:
    def __init__(self, client: ReviewerModelClient, budget: ApiBudgetTracker) -> None:
        self._client = client
        self._budget = budget

    async def review(
        self,
        task: str,
        files: list[GeneratedFile],
        test_result: TestRunResult | None,
    ) -> ReviewResult:
        self._budget.reserve_call("reviewer review")
        return await self._client.review(task, files, test_result)


class OpenAIDeveloperClient:
    def __init__(self, model: str | None = None) -> None:
        self._model = model

    async def generate_code(
        self,
        task: str,
        previous_files: list[GeneratedFile],
        test_output: str | None,
    ) -> CodeGenerationResult:
        from agents import Agent, Runner

        agent_kwargs = {
            "name": "DeveloperAgent",
            "instructions": DEVELOPER_INSTRUCTIONS,
            "output_type": CodeGenerationResult,
        }
        if self._model:
            agent_kwargs["model"] = self._model
        agent = Agent(**agent_kwargs)
        result = await Runner.run(agent, _developer_prompt(task, previous_files, test_output))
        return CodeGenerationResult.model_validate(result.final_output)


class OpenAIReviewerClient:
    def __init__(self, model: str | None = None) -> None:
        self._model = model

    async def review(
        self,
        task: str,
        files: list[GeneratedFile],
        test_result: TestRunResult | None,
    ) -> ReviewResult:
        from agents import Agent, Runner

        agent_kwargs = {
            "name": "ReviewerAgent",
            "instructions": REVIEWER_INSTRUCTIONS,
            "output_type": ReviewResult,
        }
        if self._model:
            agent_kwargs["model"] = self._model
        agent = Agent(**agent_kwargs)
        result = await Runner.run(agent, _reviewer_prompt(task, files, test_result))
        return ReviewResult.model_validate(result.final_output)


DEVELOPER_INSTRUCTIONS = """
You generate Python source code for a designated workspace.
Return only structured output matching the schema.
Do not include shell commands.
Do not request filesystem access outside the workspace.
Prefer small, readable Python modules that satisfy the provided pytest tests.
Files under tests/ are fixed, read-only context. Never return or modify those files.
When test output is provided, explain the change briefly and return corrected files.
"""

REVIEWER_INSTRUCTIONS = """
You independently review the final Python implementation.
Return structured feedback only.
Focus on correctness, edge cases, maintainability, and whether the tests appear satisfied.
Do not suggest running shell commands.
"""


def _developer_prompt(
    task: str,
    previous_files: list[GeneratedFile],
    test_output: str | None,
) -> str:
    previous = "\n\n".join(
        f"### {file.path}\n```python\n{file.content}\n```" for file in previous_files
    )
    failure = test_output or "No test output yet. This is the first implementation attempt."
    return f"""
Task:
{task}

Existing workspace Python files:
{previous or "None"}

Pytest output to address:
{failure}

Return all files that should exist in the workspace for this attempt.
"""


def _reviewer_prompt(
    task: str,
    files: list[GeneratedFile],
    test_result: TestRunResult | None,
) -> str:
    file_text = "\n\n".join(f"### {file.path}\n```python\n{file.content}\n```" for file in files)
    if test_result is None:
        test_text = "No test result was produced."
    else:
        test_text = (
            f"command: {' '.join(test_result.command)}\n"
            f"exit_code: {test_result.exit_code}\n"
            f"skipped: {test_result.skipped}\n"
            f"timed_out: {test_result.timed_out}\n"
            f"{test_result.combined_output()}"
        )
    return f"""
Task:
{task}

Final files:
{file_text or "No files were generated."}

Test result:
{test_text}
"""
