# AutoDev Architecture

## Components

`DeveloperAgent` wraps a model client that uses the OpenAI Agents SDK with a Pydantic `CodeGenerationResult` output type. It receives the user task, previous generated files, and failing pytest output.

`TestRunner` owns a fixed pytest command. It delegates execution to a sandbox backend and never accepts model-generated commands.

`ReviewerAgent` wraps a separate model client that uses the OpenAI Agents SDK with a Pydantic `ReviewResult` output type. It reviews the final files independently from the developer loop.

`Workspace` is the write gate for generated files. It resolves every model-provided path under the configured workspace root and rejects absolute paths or traversal.

`tests/` is protected from model writes. Seeded tests are copied before generation and remain the fixed target for the pytest command.

`Orchestrator` coordinates attempts, logging, test execution, repair iterations, budget checks, and final success determination.

## Workflow

1. Seed deterministic tests into the workspace, if an example or test directory was provided.
2. Ask the developer agent for generated files.
3. Validate and write files inside the workspace.
4. Run the fixed pytest command through the selected sandbox backend.
5. If tests fail, pass the failure output back to the developer agent.
6. Stop after success, a skipped test run, budget exhaustion, or `max_iterations`.
7. Ask the reviewer agent for structured feedback on the final implementation.
8. Mark success only when tests passed and the reviewer approved the result.

## Sandbox Limitation

AutoDev v0.1 does not execute generated code directly on the host. The default backend is `dry_run`, which disables execution and records a skipped test result.

The Docker backend runs:

- `--network none`
- `--cpus 1`
- `--memory 256m`
- `--pids-limit 128`
- `--read-only`
- `--tmpfs /tmp:rw,noexec,nosuid,size=64m`
- a bind-mounted generated workspace at `/workspace`

Build the default runtime image with `docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .`. The image contains Python 3.11 and pytest; runtime network access stays disabled.

If Docker is unavailable, execution is skipped. Do not treat this as a complete sandbox for hostile code without additional host hardening.

## API Budget

AutoDev uses a conservative budget guard before each model call. It does not calculate provider billing from live token prices. Instead, it multiplies the configured estimated cost per model call by the number of reserved calls and stops before exceeding `AUTODEV_API_BUDGET_USD`.

## CI

GitHub Actions installs the package with development dependencies, runs Ruff, and runs deterministic unit tests. Tests use fake model clients and fake sandbox backends, so no OpenAI API key is required.
