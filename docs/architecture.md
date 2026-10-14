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
- `--user 65534:65534`
- `--pull never`
- `--cpus 1`
- `--memory 256m`
- `--memory-swap 256m`
- `--pids-limit 128`
- `--read-only`
- `--cap-drop ALL` and `--security-opt no-new-privileges`
- `--log-driver none` and `--ulimit nofile=256:256`
- `--tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777`
- a read-only bind-mounted generated workspace at `/workspace`

The fixed pytest command remains unchanged. Container environment settings disable bytecode writes, pytest's cache, and third-party plugin autoloading so standard tests run against the read-only workspace. Tests that need temporary files must use `/tmp`, such as through pytest's `tmp_path` fixture.

Each container receives a unique name. AutoDev kills the Docker CLI on timeout and attempts `docker rm --force` in a `finally` block, including when the caller is interrupted. Cleanup failure disables success; investigate the reported container before resuming execution. Python retains a bounded prefix of stdout and stderr while draining the pipes, and Docker does not persist container logs.

Build the default runtime image with `docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .`. The image contains Python 3.11 and pytest; runtime network access stays disabled.

If Docker is unavailable, execution is skipped. Do not treat this as a complete sandbox for hostile code without additional host hardening.

The regression tests inspect Docker arguments and mock container lifecycle calls. They do not verify kernel isolation, network denial, or resource enforcement. A live Docker daemon was unavailable during this review, so these runtime properties remain unverified. Use only a trusted local Linux image and a dedicated workspace without secrets. Read-only tests also do not prevent generated Python from manipulating pytest in-process; test success is not proof that hostile code is correct.

## API Budget

AutoDev uses a conservative budget guard before each model call. It does not calculate provider billing from live token prices. Instead, it multiplies the configured estimated cost per model call by the number of reserved calls and stops before exceeding `AUTODEV_API_BUDGET_USD`.

## CI

GitHub Actions installs the package with development dependencies, runs Ruff, and runs deterministic unit tests. Tests use fake model clients and fake sandbox backends, so no OpenAI API key is required.
