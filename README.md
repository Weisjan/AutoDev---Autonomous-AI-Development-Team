# AutoDev v0.1.1

AutoDev is a small Python application where AI agents generate Python code, run a fixed pytest command in a sandbox backend, use failures for up to three repair attempts, and ask a separate reviewer agent for structured feedback.

The default model provider is **Codex CLI**, using your existing ChatGPT login without an OpenAI API key. The existing `openai_api` backend is optional and must be explicitly selected. AutoDev never switches to it after a Codex failure. Development remains sequential.

## Current Safety Posture

AutoDev never runs shell commands suggested by a model. The only test command is the predefined command in `autodev.runner.DEFAULT_PYTEST_COMMAND`.

Generated files are written only inside the configured workspace directory. Paths are validated to reject absolute paths and `..` traversal.

The `tests/` directory is protected from model writes, so generated code cannot rewrite the fixed tests it is judged against.

Execution is disabled by default through `dry_run`. The only implemented execution backend is Docker, configured with no network, a non-root user, resource limits, and read-only container and workspace filesystems. The runtime image must be built locally; AutoDev does not pull images during execution. If Docker is unavailable, test execution is skipped and the workflow reports that limitation. Docker is not a substitute for a hardened isolation environment for hostile code.

Container cleanup is attempted after each run, including timeouts. A cleanup failure prevents a successful workflow result and is reported for manual investigation. Output retention is bounded, and Docker log storage is disabled.

AutoDev never auto-pushes or auto-merges changes.

Codex runs through asynchronous subprocesses with `--sandbox read-only` and approval policy `never`. Shell execution, shell snapshots, web search, and parallel agents are disabled. Each call runs in a temporary directory containing only its JSON response schema; prompts go through stdin and responses stay in memory. Only AutoDev's validated `Workspace` layer writes generated source files.

AutoDev does not read, extract, copy, or store authentication tokens. Codex manages its own existing login. API credential environment variables are not forwarded, and the CLI is restricted to ChatGPT authentication. User configuration and execution rules are ignored for these calls to prevent custom providers or settings from changing the execution policy. The `CODEX_HOME` directory setting is preserved so Codex can locate its existing login; AutoDev does not copy credentials there.

## Windows 11 Setup (PowerShell, Python 3.12)

If Codex CLI is not already installed, install it using Node.js/npm. Verify that you have a current version supporting `--output-schema`, `--ignore-user-config`, `--ignore-rules`, and `--ephemeral`:

```powershell
npm install -g @openai/codex
codex --version
codex exec --help
codex login status
```

Keep your existing ChatGPT login. If it is missing or expired, run `codex login` and complete the ChatGPT browser sign-in. Do not use API-key login for this provider. See the official [authentication guide](https://developers.openai.com/codex/auth) and [non-interactive CLI guide](https://developers.openai.com/codex/noninteractive).

From the repository directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
```

Leave `AUTODEV_PROVIDER=codex_cli` in `.env`; no API key is needed. Run AutoDev as the same Windows user and with the same `CODEX_HOME` setting used for your Codex login. If PowerShell blocks activation, use `.\.venv\Scripts\python.exe -m pip` and `.\.venv\Scripts\autodev.exe` directly.

AutoDev resolves npm's Windows `codex.cmd` launcher to its packaged native binary and launches it without a shell. If Codex is not on PATH or the package layout differs, set `$env:AUTODEV_CODEX_EXECUTABLE = 'C:\path\to\codex.exe'`.

Leave `AUTODEV_DEVELOPER_MODEL` and `AUTODEV_REVIEWER_MODEL` empty for the CLI's built-in default, or set a model available to your ChatGPT account. AutoDev ignores custom Codex user profiles. Live model calls require connectivity and remain subject to ChatGPT usage limits.

## Run The Calculator Example

Dry-run mode writes generated files and review output but does not execute generated code:

```powershell
autodev run --example calculator --provider codex_cli --sandbox-backend dry_run
```

To run tests in Docker:

```powershell
docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .
autodev run --example calculator --provider codex_cli --sandbox-backend docker
```

The calculator example seeds `examples/calculator/tests/test_calculator.py` into the generated workspace. The fixed pytest command is:

```text
python -m pytest tests --tb=short -q
```

For a custom task:

```powershell
autodev run --task "Implement a small Python calculator module" --provider codex_cli
```

`--provider` overrides `AUTODEV_PROVIDER`; omitting both selects `codex_cli`.

## Provider Settings And Errors

`AUTODEV_CODEX_TIMEOUT_SECONDS` defaults to 180 seconds per call. `AUTODEV_CODEX_MAX_OUTPUT_BYTES` defaults to 1,000,000 bytes; retained stderr is capped at 16,000 bytes. Final JSON on stdout must pass strict Pydantic validation, including generated-file path validation. Raw subprocess diagnostics and validation inputs are not printed or stored by AutoDev.

Missing executables, startup or authentication failures, nonzero exits, timeouts, oversized output, and malformed responses stop the run with an error. Timeout and cancellation cleanup kills and reaps the subprocess. That call's output is not applied; files validated on previous attempts remain in the workspace. Reauthenticate through `codex login` when needed, or check CLI installation, supported flags, connectivity, and usage limits. There is no automatic provider fallback.

The existing conservative model-call budget guard and three-attempt limit remain active. For Codex, `AUTODEV_API_BUDGET_USD` and `AUTODEV_ESTIMATED_COST_PER_MODEL_CALL_USD` serve as a call-count guard; they do not measure ChatGPT usage or cause API billing.

The optional paid backend requires explicit installation and selection:

```powershell
python -m pip install -e ".[openai_api]"
# Configure OPENAI_API_KEY yourself only if you intend to use this paid backend.
autodev run --example calculator --provider openai_api
```

## Run Checks

```powershell
ruff check .
pytest
```

Tests mock subprocesses or model clients and need no API key, Codex login, Docker daemon, or network access. On Windows, if pytest cannot access its default temporary directory or cache, use a fresh dedicated scratch directory:

```powershell
python -m pytest --basetemp .autodev/pytest-temp-v011 -p no:cacheprovider
```

Pytest clears its `--basetemp` directory, so reserve it only for test scratch files.

## Architecture

See [docs/architecture.md](docs/architecture.md).
