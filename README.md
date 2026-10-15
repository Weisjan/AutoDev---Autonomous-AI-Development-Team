# AutoDev v0.3

AutoDev is a small Python application where AI agents generate Python code, run a fixed pytest command in a sandbox backend, use failures for up to three repair attempts, and ask a separate reviewer agent for structured feedback.

The default model provider is **Codex CLI**, using your existing ChatGPT login without an OpenAI API key. The existing `openai_api` backend is optional for sequential runs. AutoDev never switches to it after a Codex failure. Sequential development remains the default; `--parallel` enables up to two concurrent Codex developers.

## Local web dashboard (Windows PowerShell)

The optional v0.3 dashboard provides a React/TypeScript interface backed by FastAPI and the
existing parallel orchestrator. Dashboard runs always use Codex CLI and Docker. The sequential
and parallel terminal interfaces below remain available.

Prerequisites: Python 3.12, Node.js **22.12 or newer in the 22.x line, or Node 24+**,
Git, Docker Desktop running Linux containers, and your existing Codex ChatGPT login.
From the AutoDev checkout, install the optional web dependencies and build the sandbox:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,web,web_test]"
docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .
codex login status
```

Start the API in the first PowerShell window, registering each repository the UI may access:

```powershell
Set-Location 'D:\Projects\AutoDev---Autonomous-AI-Development-Team'
.\.venv\Scripts\python.exe -m autodev.web --repo 'D:\Projects\AutoDev---Autonomous-AI-Development-Team'
```

The default address is `http://127.0.0.1:8000`. Repeat `--repo 'D:\Projects\another-project'`
to register additional local Git repository roots. The CLI accepts only loopback bind addresses.
Use the same Windows user and Codex environment as your working CLI login. The dashboard
never reads or copies ChatGPT credentials and never falls back to the OpenAI API.

Start the frontend in a second PowerShell window:

```powershell
Set-Location 'D:\Projects\AutoDev---Autonomous-AI-Development-Team\frontend'
npm ci
npm run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to the localhost backend; open the frontend
using this address consistently. To use a different backend port, pass `--port 8002` and set
`$env:AUTODEV_API_PORT = '8002'` before starting Vite. Ports 5173 and 8000 must be free for
the default commands. The backend and frontend are separate processes; `npm run build`
also checks TypeScript and creates an ignored `frontend/dist/` build.

For the first **real** run:

1. Use a clean tracked Git checkout. Commit your own work manually first; AutoDev never
   commits your source checkout on your behalf. Untracked files are not copied to agents.
2. In **New Task**, choose the registered repository and select **Use the bundled two-module
   demonstration**. Keep two developers and the default bounded limits, then start the workflow.
3. Watch the actual developer start/finish events, integration, Docker pytest/Ruff output and
   final reviewer feedback. A supplied demonstration plan skips a model planning call.
4. Download the JSON report and inspect both generated modules and the retained integration
   branch/commit. Any Git merge or push remains a separate manual action.

Custom requests use the real TaskPlanner. v0.2 scope rules still apply: agents own exact Python
implementation paths; tests/control files stay protected. Custom repositories must already contain
trusted acceptance tests and dependencies compatible with the sandbox image. Rebuild the image
when runtime/development requirements, lockfile, Dockerfile or environment preflight change;
the UI does not download dependencies or rebuild images during offline validation.

**Dashboard behavior and limits:** one active workflow per backend process, up to two simultaneous
developers, no queue, no automatic resume after process termination. History imports existing
`.autodev/runs/*/report.json` files from registered repositories. Dashboard metadata lives in ignored
`.autodev/dashboard/`; unfinished runs are shown as interrupted after restart. Existing reports are
never deleted or rewritten by history loading. Live SSE notifications have a three-second polling
fallback. Task counts, timestamps and final durations are measured; no progress percentage is
estimated. Test stdout/stderr is displayed after each check finishes; raw Codex stdout/token streams
are not exposed. Integration timestamps are available in the activity log; older reports may lack it.

Cancellation stops orchestration/model work and waits for the current bounded Docker check and
cleanup before permitting another run. Worktrees/commits remain for inspection. Forced process
termination can leave resources to inspect manually. The UI's repository selector only lists startup
allowlisted roots; it cannot browse unrelated local folders. File previews are limited to owned Python
files in the canonical integration worktree, capped at 256 KB and rejected through symlinks/junctions.
Responses redact common credential patterns. Loopback peer/Host/Origin checks, an HttpOnly
SameSite session cookie, and a separate dashboard CSRF token protect browser requests. This is
a single-user local tool, not an internet-facing service; do not expose it through a tunnel or a proxy.

### Dashboard checks (no online model access)

```powershell
# From the repository root; use a fresh temp directory outside source directories.
$dashboardTestTemp = Join-Path $env:TEMP ('autodev-pytest-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest --basetemp $dashboardTestTemp -p no:cacheprovider
Set-Location frontend
npm run typecheck
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

Stop any servers on 5173/8001 before the E2E test. Its dedicated test-only server uses mocked
models/checks and a fresh temporary Git repository, while exercising real planning orchestration,
overlapping developer calls, worktrees, commits, integration, reports and the browser interface.
It never calls ChatGPT or Docker, and clearly labels mock validation output. Production has no
mock-provider environment switch. Backend dashboard tests require the optional `web,web_test`
extras; the core Docker image continues to run the v0.2 suite without web dependencies.

## Current Safety Posture

AutoDev never runs shell commands suggested by a model. The only test command is the predefined command in `autodev.runner.DEFAULT_PYTEST_COMMAND`.

Generated files are written only inside the configured workspace directory. Paths are validated to reject absolute paths and `..` traversal.

The `tests/` directory is protected from model writes, so generated code cannot rewrite the fixed tests it is judged against.

Execution is disabled by default through `dry_run`. The only implemented execution backend is Docker, configured with no network, a non-root user, resource limits, and read-only container and workspace filesystems. The runtime image must be built locally; AutoDev does not pull images during execution. If Docker is unavailable, test execution is skipped and the workflow reports that limitation. Docker is not a substitute for a hardened isolation environment for hostile code.

Container cleanup is attempted after each run, including timeouts. A cleanup failure prevents a successful workflow result and is reported for manual investigation. Output retention is bounded, and Docker log storage is disabled.

AutoDev never auto-pushes or auto-merges changes.

Codex runs through asynchronous subprocesses with `--sandbox read-only` and approval policy `never`. Shell execution, shell snapshots, web search, and Codex's internal parallel agents are disabled. AutoDev schedules its own independent processes. Sequential calls use a temporary working directory; parallel developers use their assigned Git worktrees. Schemas are temporary files, prompts go through stdin, and responses stay in memory. Only AutoDev's validated `Workspace` layer writes generated source files.

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

To run tests in Docker, build the current image first (editing the Dockerfile does not update an existing local tag):

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

## First Parallel Demonstration

Install Git for Windows and Docker Desktop with Linux containers alongside Python 3.12 and Codex CLI. Keep the repository path reasonably short to avoid Windows path-length limitations. Rebuild the sandbox image, which now includes Ruff and AutoDev's Pydantic/dotenv dependencies:

```powershell
python -m pip install -e ".[dev]"
docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .
```

Parallel development starts from committed `HEAD`. Review and commit or stash tracked changes yourself first; AutoDev refuses a dirty tracked checkout. This implementation is left uncommitted for your review. Untracked files, including `.env`, are left untouched and are not copied into worktrees.

```powershell
autodev run --parallel --example parallel-demo --provider codex_cli --concurrency 2 --plan-file examples/parallel/plan.json --sandbox-backend docker
```

One developer owns `parallel_arithmetic.py`; the other owns `parallel_text.py`. Fixed acceptance tests check addition, multiplication, and slugification, including negatives, zero, floats, punctuation, and empty text. They are seeded into the integration worktree. The agents run concurrently in separate worktrees, and AutoDev commits their validated output and cherry-picks it onto `autodev/<run-id>/integration`. A Docker dependency preflight precedes pytest and Ruff, followed by review when both checks pass. Genuine code failures return to the responsible owners for up to three correction rounds; ambiguous code failures go to all candidate owners. Infrastructure failures stop immediately without developer corrections or final review.

Omit `--plan-file` to ask TaskPlanner to decompose the request. For another repository, use `--repo C:\path\to\repo --task "..."` with a committed baseline and fixed tests under `tests/`. Initial ownership supports exact Python implementation file paths, with tests, configuration, hidden files, and overlapping paths excluded. Agree on shared interfaces before coding; ordered dependencies need separate runs or the sequential workflow.

For an offline demonstration:

```powershell
python -m pytest tests/test_parallel.py tests/test_integration.py --basetemp .autodev/pytest-parallel-demo -p no:cacheprovider -v
```

The overlap test blocks the first two mock model calls until both have entered, then verifies overlapping intervals and a peak of two. An end-to-end offline test uses real Git worktrees and mocked models/checks, verifies a correction commit and final review, and leaves source `main` unchanged. This proves scheduler overlap, without claiming live model throughput.

## Parallel Limits And Reports

| Environment setting | Default | CLI override |
| --- | --- | --- |
| `AUTODEV_CONCURRENCY` | 2, maximum 2 | `--concurrency` |
| `AUTODEV_MAX_TASKS` | 4, maximum 8 | `--max-tasks` |
| `AUTODEV_MAX_CORRECTIONS` | 3 after initial generation, maximum 3 | `--max-corrections` |
| `AUTODEV_MAX_MODEL_CALLS` | 24 across all agents | `--max-model-calls` |
| `AUTODEV_WORKFLOW_TIMEOUT_SECONDS` | 1800 | `--workflow-timeout` |
| `AUTODEV_AGENT_TIMEOUT_SECONDS` | 240 | environment |
| `AUTODEV_GIT_TIMEOUT_SECONDS` | 30 | environment |

The existing estimated model-call budget also applies, and may stop large plans before the correction limit. Its USD estimate does not measure ChatGPT usage or trigger API billing. Provider, agent, Git, and workflow deadlines are separate. A workflow deadline cancels model subprocesses; an already-running Docker check completes its own bounded timeout and cleanup before Python's executor exits.

Worktrees live under `<repo>/.autodev/runs/<run-id>/`; task branches are `autodev/<run-id>/task-<task-id>`. JSON is printed to stdout and saved as `report.json` in the run directory. It includes the validated plan, ownership, agent IDs, execution timestamps/durations, source/integration commits, correction rounds, pytest/Ruff results, review, conflicts, and final status. Failed/unverified parallel runs exit with code 1. Dry-run cannot claim verified success or trigger final review.

Branches and worktrees are retained on success and failure. Inspect the report and integration diff before deciding what to merge. Conflicts preserve the cherry-pick state for manual inspection. AutoDev never pushes, merges into `main`, approves PRs, resets the source checkout, or deletes branches/worktrees. Git hooks and filesystem monitors are disabled for workflow commands; model-provided commands are never executed.

Git worktrees share metadata and are not security sandboxes. Codex stays read-only, and generated code executes only under the existing Docker restrictions. Tracked credential paths, symlinks, submodules, Git filters, and custom merge drivers are refused by this initial implementation. If a managed environment denies Git metadata writes, worktree creation, or Docker access, obtain explicit permission there first; AutoDev does not elevate or broaden permissions automatically. ChatGPT rate/usage limits stop the affected batch; retry later, with no token handling or paid fallback.

## Rebuilding And Diagnosing The Docker Test Environment

The image uses a digest-pinned Python base and `docker/sandbox/requirements.lock` with exact versions and wheel SHA256 hashes, following [Docker's pinned-base guidance](https://docs.docker.com/build/building/best-practices/) and [pip's hash-checking installation guidance](https://pip.pypa.io/en/stable/topics/secure-installs/). The lock covers runtime, development, transitive, and build dependencies for Python 3.11 on Linux amd64/arm64. AutoDev is installed with `.[dev]` using the already-locked packages and build backend; `pip check` and a dependency smoke check must pass during the build. The optional `openai_api` extra is excluded.

Rebuild whenever the Dockerfile, lock, preflight script, `pyproject.toml` dependencies/build metadata, or baked AutoDev source changes, and before using an older sandbox tag with a new release. If dependencies change, deliberately update the pinned versions/hashes in the lock; the lock-coverage regression test and image build catch missing/incompatible entries. Review base-digest and lock updates before applying them. Editing files alone never rebuilds the image. Confirm `AUTODEV_DOCKER_IMAGE` points to the tag you rebuilt:

```powershell
docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .
docker image inspect autodev-sandbox:py311 --format '{{.Id}} {{.Created}}'
```

Normal builds correctly invalidate changed layers. If diagnosing an uncertain cache, add `--no-cache` to that build command. Network access is permitted only at image build time; AutoDev never downloads images or installs dependencies during validation. The build context allows only project metadata, source, and sandbox build inputs, excluding credentials, `.env`, Git metadata, reports, and worktrees.

Before parallel checks, the trusted image preflight runs using `python -I` so workspace modules cannot shadow its dependencies. It verifies installed AutoDev runtime/dev requirements and the integrated repository's declared runtime/dev dependencies and version constraints. A stale image missing the preflight script also fails safely. Other projects needing additional dependencies require a reviewed project-specific image and lock, selected with `AUTODEV_DOCKER_IMAGE`.

Results contain `failure_kind: "infrastructure"` or `"code"` (null on success), and the JSON report includes the environment preflight result. Missing installed dependencies or validation executables, failed Docker startup/cleanup, and validation-tool configuration/internal errors produce `integration_status: "infrastructure_failed"`; no correction round or review is requested. Resolve/rebuild the environment before retrying the workflow. Assertion failures, source syntax errors, missing generated modules such as `parallel_text`, and Ruff lint findings remain code failures and use the bounded correction loop. Dry-run remains unverified and does not claim success.
