# AutoDev v0.1

AutoDev is a small Python application where AI agents generate Python code, run a fixed pytest command in a sandbox backend, use failures for up to three repair attempts, and ask a separate reviewer agent for structured feedback.

## Current Safety Posture

AutoDev never runs shell commands suggested by a model. The only test command is the predefined command in `autodev.runner.DEFAULT_PYTEST_COMMAND`.

Generated files are written only inside the configured workspace directory. Paths are validated to reject absolute paths and `..` traversal.

The `tests/` directory is protected from model writes, so generated code cannot rewrite the fixed tests it is judged against.

Execution is disabled by default through `dry_run`. The only implemented execution backend is Docker, configured with no network, a non-root user, resource limits, and read-only container and workspace filesystems. The runtime image must be built locally; AutoDev does not pull images during execution. If Docker is unavailable, test execution is skipped and the workflow reports that limitation. Docker is not a substitute for a hardened isolation environment for hostile code.

Container cleanup is attempted after each run, including timeouts. A cleanup failure prevents a successful workflow result and is reported for manual investigation. Output retention is bounded, and Docker log storage is disabled.

AutoDev never auto-pushes or auto-merges changes.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
```

Set `OPENAI_API_KEY` in your shell or `.env` before making real model calls. CI tests mock model calls and do not require API secrets.

## Run The Calculator Example

Dry-run mode writes generated files and review output but does not execute generated code:

```powershell
autodev run --example calculator --sandbox-backend dry_run
```

To run tests in Docker:

```powershell
docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .
autodev run --example calculator --sandbox-backend docker
```

The calculator example seeds `examples/calculator/tests/test_calculator.py` into the generated workspace. The fixed pytest command is:

```text
python -m pytest tests --tb=short -q
```

## Run Checks

```powershell
ruff check .
pytest
```

## Architecture

See [docs/architecture.md](docs/architecture.md).
