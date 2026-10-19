# AutoDev v0.5 — Phase 1

AutoDev is a small Python application where AI agents generate Python code, run a fixed pytest command in a sandbox backend, use failures for up to three repair attempts, and ask a separate reviewer agent for structured feedback.

The default model provider is **Codex CLI**, using your existing ChatGPT login without an OpenAI API key. The existing `openai_api` backend is optional for sequential runs. AutoDev never switches to it after a Codex failure. Sequential development remains the default; `--parallel` enables up to two concurrent Codex developers.

## Role-based models and reasoning (v0.5 Phase 1)

New dashboard runs explicitly select **Balanced**. In **New Task**, choose a preset and optionally
customize Architect, Developers and Reviewer separately. All parallel workers use the resolved
Developers settings. The independent-task Planner uses the Architect settings.

| Preset | Architect | Developers | Reviewer |
| --- | --- | --- | --- |
| Fast | `gpt-6.1-sol` / `medium` | `gpt-6.1-sol` / `low` | `gpt-6.1-sol` / `medium` |
| Balanced | `gpt-6-astra` / `high` | `gpt-6.1-sol` / `high` | `gpt-6-astra` / `high` |
| Maximum Quality | `gpt-6-astra` / `xhigh` | `gpt-6.1-sol` / `xhigh` | `gpt-6-astra` / `xhigh` |

`xhigh` means extra-high reasoning. These are **requested settings**, not proof of account access
or actual runtime model identity. AutoDev does not inspect credentials or probe models before a
run. Codex handles your existing ChatGPT login. The dashboard and JSON report keep requested
settings separate from runtime observations, which are **unavailable** with the current transport.
No model self-report is treated as verification. Unsupported/inaccessible choices stop with an
explicit error; AutoDev never substitutes another model, reasoning level or provider.

Presets do not increase timeouts, concurrency, correction rounds or model-call budgets. Maximum
Quality can therefore time out under the same limits. Codex tools and internal sub-agents remain
disabled; Git worktree ownership, protected tests and Docker restrictions remain in force.

Existing CLI/API calls without a new policy retain legacy defaults, including Architect inheritance
from the Developer model and no explicit reasoning argument. New policies are opt-in outside the
dashboard. For example, **when you choose to make a real Codex call**, in Windows PowerShell:

```powershell
# Uses ChatGPT sign-in, no API key. This command consumes Codex usage.
.\.venv\Scripts\python.exe -m autodev run --example calculator --sandbox-backend docker --model-preset balanced
# Optional override for one role; all other roles keep the preset settings.
.\.venv\Scripts\python.exe -m autodev run --example calculator --sandbox-backend docker --model-preset fast --reviewer-reasoning-effort high
```

Environment equivalents are documented in [.env.example](.env.example). Preset settings resolve
once into a versioned immutable run snapshot. Project resume retains that snapshot and all prior
limits; existing v0.4 checkpoint checksums remain supported. See [role model configuration](docs/v0.5-role-models.md)
for precedence, API examples, error categories, limitations and the bounded real verification plan.

## Multi-stage projects (v0.4 Phase 1)

In the dashboard's **New Task → Workflow type**, select **Multi-stage project**. The existing
independent-task mode remains available. Project mode uses the real Codex provider and existing
Docker sandbox; no API key or additional service is needed. Backend/frontend startup commands
are in the next section.

The Project Architect produces a validated specification with technology stack, repository file
structure, components, interface contracts, tasks, dependencies, ordered milestones, acceptance
criteria, testing requirements, risks and assumptions. The dashboard displays the specification,
task dependency graph, actual agent attempts, milestone status, validation output and checkpoints.
Plans are limited to 8 tasks (or the configured lower limit), 4 milestones, 80 structure paths and
100 KB of specification JSON. Cycles, missing/later-stage dependencies, inconsistent component
references, unsafe paths and unordered overlapping ownership are rejected before developer work.

For architect JSON/schema diagnostics and recovery from a failed planning call, see
[the structured-output investigation](docs/architect-output-diagnostics.md).

Independent ready tasks run concurrently, up to two developers. Each batch starts in new isolated
Git worktrees based on the **current integration commit**. Dependencies become available only after
their commits are integrated and their selected trusted tests plus Ruff pass. Previously validated
task tests remain in later checks; completed milestone tests are cumulative. Each milestone gets
a retained commit/checkpoint. The final complete pytest suite and Ruff must pass before final review.
Corrections are bounded to three per batch and use the existing error classification: infrastructure
failures never trigger developer corrections. Integration conflicts stop execution and retain state.

Project-mode Ruff checks apply the full fixed rule set to **all integrated task-owned Python
files**, cumulatively across milestones. Protected tests and unrelated baseline files remain
outside that lint scope; their functional pytest checks still run unchanged, including the final
complete suite. Reports include the exact Ruff command and scope. Baseline lint failures never
trigger developer corrections. See [validation and milestone scheduling](docs/project-validation.md)
for failure classes, the three-stage invoice schedule and verification details.

**Phase 1 execution scope:** Python repositories with existing trusted tests and preinstalled
sandbox dependencies. Tasks may write Python implementation, Markdown, JSON data, plain text and
static HTML/CSS files. Existing tests, hidden files, dependency manifests, shell scripts and control
configuration remain protected. JSON output is parsed as data before writing. This phase does not
bootstrap arbitrary language toolchains, generate authoritative tests, install model-selected
dependencies, build generated React/Node projects, launch generated services or execute generated
code on the host. The existing AutoDev React dashboard is supported and unchanged as a stack.

For a first real project demonstration, prepare a **new** separate repository with the bundled
trusted tests. From the AutoDev root in PowerShell (choose an unused destination):

```powershell
$autoDevRoot = (Get-Location).Path
$demoRoot = 'D:\Projects\AutoDev-Invoice-Demo'
New-Item -ItemType Directory -Path $demoRoot -ErrorAction Stop
Copy-Item -Path (Join-Path $autoDevRoot 'examples\project\tests') -Destination $demoRoot -Recurse
Set-Content -Path (Join-Path $demoRoot '.gitignore') -Value '.autodev/' -Encoding ascii
git -C $demoRoot init
git -C $demoRoot add .gitignore tests
git -C $demoRoot commit -m 'Add trusted project acceptance tests'
Get-Content (Join-Path $autoDevRoot 'examples\project\task.md') -Raw
# Start the API with access to that repository:
.\.venv\Scripts\python.exe -m autodev.web --repo $demoRoot
```

These are commands **you** run to prepare/commit the trusted fixture, not operations the dashboard
runs on your source checkout. Start the frontend as below, select the demo repository and project
mode, paste `examples/project/task.md` into Task instructions, and start. Watch two independent core
tasks, the dependent application, then documentation. Task tests must be separated into files that
can pass at their stage; a single file importing all future components cannot serve an early stage.
Docker Desktop must be running and the sandbox image built before validation.

**Pause and recovery:** Pause requests finish the current integration/test batch, then stop at a
verified checkpoint. Final review cannot be paused once started; cancellation is still available.
Paused projects can resume after reviewing the checkpoint and explicitly confirming **Verify and
resume project**. Backend restart loads project reports and checkpoint history from
`.autodev/runs/<id>/project_report.json` and `checkpoints/NNN.json`. Boundary interruptions are shown
as interrupted and can resume if verification passes. Already validated developer work is skipped.
Full validation may be rerun before review. Active execution time and model-call reservations carry
across resumes; changed configuration cannot reset limits.

Recovery checks checkpoint schema/checksum, source branch/HEAD, integration commit, common Git
repository identity, worktree paths/branches/HEADs, pending Git operations, safe attributes, and
uncommitted/untracked integration/task changes. Source untracked notes remain untouched. A per-run
OS file lock prevents concurrent resume across backend processes. Checkpoints are immutable; project
reports update atomically. Source or worktree changes detected at a boundary stop the run, rather
than becoming part of an accepted checkpoint.

Mid-batch interruptions, dirty/changed worktrees, corrupt checkpoints, altered configuration and
unfinished Git operations **block automatic resume**. Inspect and recover manually, then explicitly
start a new run if needed; there is no force-resume or automatic reset/cleanup. The dashboard never
claims an unsafe recovery succeeded. Runs cancelled through the cancellation control are terminal.
Milestone checks repair only the current batch; failures requiring revisions of already validated
prerequisites stop after the configured correction limit. Cross-stage replanning, rollback, task
queues, remote execution and automatic merge/push remain unsupported. This phase is experimental,
not a production-readiness claim.

Offline verification includes the existing regression suite, project schema/DAG tests, measured
parallel overlap, dependent worktree/context checks, real Git integration, checkpoint recovery and
rejection tests, API restart/resume tests, React interactions, and browser tests for both workflows.
Mock checks are explicitly labeled as test fixtures; they do not establish live Codex or Docker
runtime behavior. Use the complete check commands in the dashboard section below.

Recorded delivery results and the complete changed-file list are in
[v0.4 Phase 1 verification](docs/v0.4-phase1-validation.md).

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

AutoDev never runs shell commands suggested by a model. Sequential and independent task runs use
the predefined command in `autodev.runner.DEFAULT_PYTEST_COMMAND`. Project stages use the same
fixed pytest executable/options with validated existing test-file paths; final validation uses
the complete predefined suite.

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
