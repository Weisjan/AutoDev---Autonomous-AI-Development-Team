from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Awaitable
from contextlib import suppress
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from autodev.agents import (
    DEVELOPER_INSTRUCTIONS,
    REVIEWER_INSTRUCTIONS,
    DeveloperModelClient,
    OpenAIDeveloperClient,
    OpenAIReviewerClient,
    ReviewerModelClient,
    _developer_prompt,
    _reviewer_prompt,
)
from autodev.config import AutoDevConfig, CodexCLIConfig
from autodev.schemas import CodeGenerationResult, GeneratedFile, ReviewResult, TestRunResult

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class ProviderError(RuntimeError):
    """A model provider failed; callers must never fall back to a paid provider."""


class ProviderAuthenticationError(ProviderError):
    """The selected provider has no valid login."""


class ProviderProcessError(ProviderError):
    """The provider could not start or exited unsuccessfully."""


class ProviderTimeoutError(ProviderError):
    """The model call exceeded its time limit."""


class ProviderResponseError(ProviderError):
    """The provider returned missing, oversized, or invalid structured output."""


class ModelProvider(DeveloperModelClient, ReviewerModelClient, Protocol):
    """Shared developer/reviewer contract, independent of transport or authentication."""


class OpenAIAPIProvider:
    """Opt-in adapter retaining the existing OpenAI Agents SDK clients."""

    def __init__(self, developer_model: str | None, reviewer_model: str | None) -> None:
        self._developer = OpenAIDeveloperClient(developer_model)
        self._reviewer = OpenAIReviewerClient(reviewer_model)

    async def generate_code(
        self, task: str, previous_files: list[GeneratedFile], test_output: str | None
    ) -> CodeGenerationResult:
        return await self._call(self._developer.generate_code(task, previous_files, test_output))

    async def review(
        self, task: str, files: list[GeneratedFile], test_result: TestRunResult | None
    ) -> ReviewResult:
        return await self._call(self._reviewer.review(task, files, test_result))

    @staticmethod
    async def _call(call: Awaitable[ResponseModel]) -> ResponseModel:
        try:
            return await call
        except ImportError:
            raise ProviderProcessError(
                'The optional openai_api backend requires: pip install -e ".[openai_api]"'
            ) from None
        except ValidationError:
            raise ProviderResponseError("OpenAI API returned invalid structured output.") from None
        except Exception as exc:
            if type(exc).__name__ == "AuthenticationError":
                raise ProviderAuthenticationError("OpenAI API authentication failed.") from None
            raise ProviderProcessError("OpenAI API model call failed.") from None


class CodexCLIProvider:
    """Use Codex's existing ChatGPT login without handling credentials in AutoDev."""

    def __init__(
        self,
        config: CodexCLIConfig,
        developer_model: str | None = None,
        reviewer_model: str | None = None,
    ) -> None:
        self._config = config
        self._developer_model = developer_model
        self._reviewer_model = reviewer_model

    async def generate_code(
        self, task: str, previous_files: list[GeneratedFile], test_output: str | None
    ) -> CodeGenerationResult:
        return await self._run(
            DEVELOPER_INSTRUCTIONS + _developer_prompt(task, previous_files, test_output),
            CodeGenerationResult,
            self._developer_model,
        )

    async def review(
        self, task: str, files: list[GeneratedFile], test_result: TestRunResult | None
    ) -> ReviewResult:
        return await self._run(
            REVIEWER_INSTRUCTIONS + _reviewer_prompt(task, files, test_result),
            ReviewResult,
            self._reviewer_model,
        )

    async def _run(
        self, prompt: str, response_type: type[ResponseModel], model: str | None
    ) -> ResponseModel:
        executable = _codex_executable(self._config.executable)
        # No repository, credentials, or generated files are copied into this directory.
        # Only a response schema is written here by AutoDev, never model-generated code.
        with tempfile.TemporaryDirectory(prefix="autodev-codex-") as directory:
            root = Path(directory)
            schema_path = root / "response.schema.json"
            schema_path.write_text(json.dumps(_strict_schema(response_type)), encoding="utf-8")
            command = [
                executable,
                "--ask-for-approval",
                "never",
                "exec",
                "--sandbox",
                "read-only",
                "--ignore-user-config",
                "--ignore-rules",
                "--ephemeral",
                "--skip-git-repo-check",
                "--color",
                "never",
                "--config",
                'forced_login_method="chatgpt"',
                "--config",
                'model_provider="openai"',
                "--config",
                'web_search="disabled"',
                "--disable",
                "shell_tool",
                "--disable",
                "shell_snapshot",
                "--disable",
                "multi_agent",
                "--output-schema",
                str(schema_path),
            ]
            if model:
                command.extend(["--model", model])
            command.append("-")
            prompt = (
                "Return only a JSON object matching the response schema. "
                "Do not use tools, execute commands, read credentials, or modify any files. "
                "AutoDev alone validates and writes generated source files.\n\n" + prompt
            )
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=root,
                    env=_codex_environment(),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError:
                raise ProviderProcessError(
                    "Could not start Codex CLI. Check AUTODEV_CODEX_EXECUTABLE and PATH."
                ) from None

            try:
                stdout, stderr = await asyncio.wait_for(
                    _exchange(process, prompt.encode("utf-8"), self._config.max_output_bytes),
                    timeout=self._config.timeout_seconds,
                )
            except TimeoutError:
                raise ProviderTimeoutError(
                    f"Codex CLI timed out after {self._config.timeout_seconds} seconds. "
                    "No provider fallback was attempted."
                ) from None
            except OSError:
                raise ProviderProcessError("Codex CLI subprocess communication failed.") from None
            finally:
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                    # Drain remaining buffered pipe data after killing, then reap the child.
                    await process.communicate()

            if process.returncode != 0:
                # Inspect diagnostics only to classify failure; never expose or persist them.
                diagnostic = stderr.decode("utf-8", errors="replace").lower()
                if any(
                    marker in diagnostic
                    for marker in (
                        "unauthorized",
                        "401",
                        "authentication",
                        "not logged in",
                        "login",
                        "sign in",
                        "token expired",
                        "refresh token",
                    )
                ):
                    raise ProviderAuthenticationError(
                        "Codex CLI ChatGPT authentication failed. Run `codex login` with "
                        "your ChatGPT account, then retry. No API fallback was attempted."
                    )
                raise ProviderProcessError(
                    f"Codex CLI exited with code {process.returncode}. Check installation, "
                    "CLI version, connectivity, and ChatGPT usage limits. "
                    "No provider fallback was attempted."
                )
            try:
                return response_type.model_validate_json(stdout, strict=True)
            except ValidationError:
                # Pydantic errors can contain model output; keep them out of logs/tracebacks.
                raise ProviderResponseError(
                    f"Codex CLI returned invalid JSON for {response_type.__name__}."
                ) from None


async def _exchange(
    process: asyncio.subprocess.Process, prompt: bytes, max_output_bytes: int
) -> tuple[bytes, bytes]:
    async def send() -> None:
        assert process.stdin is not None
        try:
            process.stdin.write(prompt)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Collect the exit code and stderr for the useful error classification.
        finally:
            process.stdin.close()

    async def read(stream: asyncio.StreamReader, limit: int, reject_overflow: bool) -> bytes:
        result = bytearray()
        while chunk := await stream.read(8192):
            if reject_overflow and len(result) + len(chunk) > limit:
                raise ProviderResponseError("Codex CLI response exceeded its output limit.")
            result.extend(chunk[: max(0, limit - len(result))])
        return bytes(result)

    assert process.stdout is not None and process.stderr is not None
    tasks = [
        asyncio.create_task(send()),
        asyncio.create_task(read(process.stdout, max_output_bytes, True)),
        asyncio.create_task(read(process.stderr, 16_000, False)),
        asyncio.create_task(process.wait()),
    ]
    try:
        _, stdout, stderr, _ = await asyncio.gather(*tasks)
        return stdout, stderr
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _strict_schema(response_type: type[BaseModel]) -> dict:
    """Codex structured output requires every property, including nullable ones."""
    schema = response_type.model_json_schema()

    def visit(value) -> None:
        if isinstance(value, dict):
            value.pop("default", None)
            if value.get("type") == "object":
                value["additionalProperties"] = False
                value["required"] = list(value.get("properties", {}))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)
    return schema


def _codex_environment() -> dict[str, str]:
    # Read only ordinary OS/path settings. Never read/copy API keys or auth tokens.
    allowed = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "TMPDIR",
        "CODEX_HOME",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    }
    return {key: os.environ[key] for key in os.environ if key.upper() in allowed}


def _codex_executable(configured: str) -> str:
    executable = shutil.which(configured)
    if executable is None:
        raise ProviderProcessError(
            "Codex CLI was not found. Install it and set AUTODEV_CODEX_EXECUTABLE if needed."
        )
    path = Path(executable).resolve()
    if sys.platform == "win32" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # npm's Windows launcher is a shell script. Invoke its packaged native binary
        # directly, so prompts never touch cmd/PowerShell and timeout kills the real process.
        packages = path.parent / "node_modules" / "@openai"
        for package in ("codex", "codex-win32-x64", "codex-win32-arm64"):
            for target in ("x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"):
                native = packages / package / "vendor" / target / "codex" / "codex.exe"
                if native.is_file():
                    return str(native)
        raise ProviderProcessError(
            "Cannot locate Codex's native Windows binary. Set AUTODEV_CODEX_EXECUTABLE "
            "to codex.exe or reinstall Codex CLI."
        )
    return str(path)


def build_provider(config: AutoDevConfig) -> ModelProvider:
    if config.provider == "codex_cli":
        return CodexCLIProvider(
            config.codex_cli, config.agents.developer_model, config.agents.reviewer_model
        )
    if config.provider == "openai_api":
        return OpenAIAPIProvider(config.agents.developer_model, config.agents.reviewer_model)
    raise ProviderError(f"Unsupported model provider: {config.provider}")
