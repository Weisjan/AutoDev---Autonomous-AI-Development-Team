# AutoDev Architecture

## v0.5 Phase 1 role model configuration

`model_policy.py` defines frozen, extra-forbidden Pydantic selection, override and resolved policy
types. Three versioned presets configure Architect/Planner, Developers and Reviewer separately.
Resolution applies preset values, explicit operator overrides, then per-run overrides. With no
new policy, resolution preserves legacy developer/reviewer model names, Architect inheritance and
unspecified reasoning. A saved resolved snapshot is returned directly, without consulting presets.

The dashboard posts an explicit Balanced selection by default. The API validates this separately
from its existing allowlisted workflow-limit fields; clients cannot supply resolved policies or
provider/execution settings. Factories resolve settings before starting model work, pass the same
immutable snapshot to all worktree providers and retain it in reports. Role selection affects only
`--model` and the TOML string `--config model_reasoning_effort="..."` argv entries. Subprocess shell
usage, environment allowlist, read-only sandbox, ChatGPT login, approval policy, disabled tools and
disabled Codex multi-agent settings are unchanged. There is no new provider or API integration.

`model_execution.py` associates each provider request with its agent attempt using an asyncio-local
ContextVar. It records a unique call ID, requested settings, lifecycle and sanitized error category.
There is no shared mutable "last model" field across concurrent agents. Runtime model/reasoning
observations are null and explicitly unavailable: the existing final-stdout structured JSON
transport supplies no trustworthy observation contract. Model-written summaries and stderr banners
are not observations. Recognized CLI rejection/fallback diagnostics cause explicit failure.
Account entitlement is never inferred from a local catalog or preset membership.

Provider configuration, model access, authentication, rate-limit, subprocess, timeout and response
failures have separate error kinds. Developer ownership/incomplete-output failures are reported
as implementation errors. Provider errors stop the batch, block queued calls, and never enter test
correction loops. Already running peers finish under the existing deadlines. No automatic retry,
model substitution, effort downgrade, budget expansion or provider fallback is introduced.

New reports use `report_version: 2`, and resolved model policies use `version: 1` and
`preset_revision: 1`. New checkpoints use envelope version 2. `CheckpointStore` verifies the raw
canonical payload checksum before typed loading, rejects duplicate keys/non-finite numbers, then
verifies the typed checksum. A version 1 projection removes only the newly defaulted metadata;
it rejects v0.5 data in that envelope and reproduces the original v0.4 digest. Legacy configuration
fingerprints retain the original model fields. Version 2 fingerprints include the resolved policy,
so saved choices survive changed preset/operator defaults. Resume compares live and checkpoint
policies and preserves all prior Git, cleanliness, budget and elapsed-time checks. Older files are
not rewritten, and no force-resume path is added.

See [configuration, compatibility and verification](v0.5-role-models.md) for exact presets, operator
precedence, API shape, test coverage and remaining runtime limitations.

## v0.4 Phase 1 project orchestration

`ProjectArchitect` uses `CodexCLIProvider.architect` and the existing structured JSON subprocess
transport to obtain a bounded `ProjectSpec`. Schema validation and a second baseline-test check
run before developer execution. Project models explicitly describe repository files, technology,
components, interfaces, tasks, milestones, acceptance/testing requirements, risks and assumptions.
They exclude arbitrary commands and execution settings. The only execution profile is Python.

The Codex schema advertises portable file/test-path constraints and bounded ownership. The
architect prompt lists exact trusted test files. Final stdout is parsed as one JSON document;
syntax/encoding failures and Pydantic schema/consistency failures have distinct provider errors.
Reports retain bounded, redacted field/rule diagnostics, with no raw response persistence or
implicit model retries. See [the incident analysis](architect-output-diagnostics.md).

`DependencyEngine` validates a DAG and selects ready tasks within the current milestone and
configured concurrency. Unordered overlapping ownership is rejected globally; ordered dependent
tasks may revise the same implementation/documentation path. `ProjectOrchestrator` reuses
`ParallelOrchestrator._develop`, Developer/Reviewer agents, budgets, provider, Git scope checks,
Workspace writes and `SandboxChecks`. Existing v0.3 task orchestration remains separate and intact.

Tasks are created lazily using the integration HEAD after prerequisite validation, rather than the
original source commit. Both filesystem context and model context therefore contain prerequisites.
Every batch integrates commits, runs validated explicit existing test-file paths in Docker, and runs
fixed Ruff. Previously validated tests remain selected and completed milestone tests are cumulative.
Project Ruff targets exact, cumulative integrated task-owned Python paths, using the same fixed
strict rules with isolated configuration, no cache and no write/fix options. Protected/unowned
baseline files are not linted by project stages. The exact command and scope remain in each report.
Unexpected Ruff diagnostics outside integrated ownership are classified as baseline failures and
stop without corrections; unattributed or earlier-milestone lint failures outside the current
repairable batch also stop for manual review. Functional pytest failures remain eligible for the
existing bounded correction policy. Infrastructure errors retain their separate classification.
The final full pytest suite is mandatory before final review. No generated code runs on the host;
JSON data parsing and file reads do not execute generated content. Infrastructure errors stop with
no corrections; code corrections are bounded to the current batch, global call/time limits and budget.

The architect no longer demands four milestones. It preserves explicit requested counts within
the four-milestone Phase 1 limit. Recognized numbered `Name: file...` headings additionally constrain
milestone name/order, file grouping and explicitly independent tasks before any developers start.
Unrecognized prose remains model-guided and receives the normal ProjectSpec/DAG validation.
Plans are rejected rather than silently regrouped. Existing scheduling already runs ready tasks
concurrently within a milestone and waits for validated integration before advancing.
See [the validation regression report](project-validation.md).

`CheckpointStore` saves immutable, checksummed Pydantic snapshots only after verifying a clean
commit boundary. Reports include milestone state, validated task IDs, task bases/attempt commits,
configuration fingerprint, calls, elapsed execution time and checkpoint history. Atomic project
reports mark an unsafe in-flight phase before new work starts. A safe resume reacquires an OS file
lock, validates checkpoint consistency and Git identity/state, restores reservations, and skips
validated tasks. An unsafe phase, changed source/worktree/configuration, wrong common Git directory,
pending Git operation or invalid checkpoint refuses resume without mutation of generated source.
There is no force override; manual recovery and explicit confirmation of a new run are required.

FastAPI accepts `mode: project` on the existing start endpoint, and adds authenticated/CSRF-protected
pause/resume endpoints. Resume requires `confirmed: true` and verifies state before scheduling,
then verifies again under the workflow lock. The dashboard shows the actual specification, dependency
edges, milestones, assignments, measured statuses, checkpoints, reports and supported controls.
All v0.3 local network/file/authentication boundaries remain in force. Project preview adds the
project-specific safe text-file allowlist; it never serves generated HTML as executable content.

Limitations and a Windows demonstration with trusted stage tests are documented in README.
Arbitrary language/package bootstrapping, generated authoritative tests, automatic replanning of
validated prerequisites, rollback, unsafe recovery, source merges and pushes are not implemented.
Offline tests use real Git with mocked models/checks, including barrier-proven overlapping work,
dependent contexts, ordered shared-file revisions, checkpoints, interruption and browser pause/resume.

## Components

`DeveloperAgent` wraps an injected model client returning a Pydantic `CodeGenerationResult`. It receives the user task, previous generated files, and failing pytest output.

`TestRunner` owns a fixed pytest command. It delegates execution to a sandbox backend and never accepts model-generated commands.

`ReviewerAgent` uses the provider's review method returning a Pydantic `ReviewResult`. It reviews the final files in a separate model call from the developer loop.

`ModelProvider` combines the developer and reviewer client protocols. `build_provider` selects `codex_cli` by default, or the explicitly configured `openai_api` adapter. The API adapter preserves the existing Agents SDK clients; its dependency is optional and imported only during API calls. No errors trigger a provider switch.

`CodexCLIProvider` invokes `codex exec` through `asyncio.create_subprocess_exec`, with no shell. Prompts go through stdin, with a temporary Pydantic-derived JSON Schema requiring all properties, including nullable fields. Final JSON on stdout is validated with `model_validate_json(strict=True)` before the Workspace receives any files. Pipes are drained concurrently with bounded retention and a per-call timeout. Timeout, cancellation, and communication failure kill/reap the subprocess. Errors omit raw subprocess diagnostics and validation inputs.

Codex runs read-only with approvals set to `never` and shell execution, snapshots, web search, and its internal parallel agents disabled. Sequential calls use a temporary directory; parallel calls use their assigned task worktree, with the response schema in a separate temporary directory. User configuration and execution rules are ignored. The CLI is restricted to the OpenAI provider and ChatGPT login, with API credential environment variables excluded. AutoDev never opens credential files or reads token values; Codex manages its existing login. The Workspace remains the only writer of generated source files. On Windows, npm launchers resolve to the packaged native binary so cleanup targets Codex directly.

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

AutoDev v0.2 does not execute generated code directly on the host. The default backend is `dry_run`, which disables execution and records a skipped test result.

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

The sequential/independent fixed pytest command remains unchanged. Project stages select validated
existing test files using the same fixed Python/pytest executable and options. Final project validation
runs the complete predefined command. Container environment settings disable bytecode writes,
pytest's cache, and third-party plugin autoloading so tests run against the read-only workspace.
Tests that need temporary files must use `/tmp`, such as through pytest's `tmp_path` fixture.

Each container receives a unique name. AutoDev kills the Docker CLI on timeout and attempts `docker rm --force` in a `finally` block, including when the caller is interrupted. Cleanup failure disables success; investigate the reported container before resuming execution. Python retains a bounded prefix of stdout and stderr while draining the pipes, and Docker does not persist container logs.

Build the default runtime image with `docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .`. The image contains Python 3.11, pytest, Ruff, Pydantic, and dotenv; runtime network access stays disabled. Parallel checks use the same container restrictions and cleanup for both fixed pytest and Ruff commands. Ruff ignores repository configuration (`--isolated`), disables caching, and uses AutoDev's explicit lint rules. Git-specific offline tests skip if Git is absent from the image.

The base image is pinned by digest. Exact, hash-verified wheel versions in `docker/sandbox/requirements.lock` cover all project runtime/dev dependencies, transitive dependencies, and the build backend. The trusted source is installed using `.[dev]`, `--no-deps`, and `--no-build-isolation` after the lock is installed. Build-time `pip check` and `check_environment.py` verify the result. The Docker context is allowlisted; credentials, environment files, Git metadata, reports, and worktrees are excluded. There is no runtime package/image download and no OpenAI API extra. Rebuild after build inputs/dependencies or baked source change; an existing image tag is not updated by changing the Dockerfile.

If Docker is unavailable, execution is skipped. Do not treat this as a complete sandbox for hostile code without additional host hardening.

The regression tests inspect Docker arguments and mock container lifecycle calls. They do not verify kernel isolation, network denial, or resource enforcement. A live Docker daemon was unavailable during this review, so these runtime properties remain unverified. Use only a trusted local Linux image and a dedicated workspace without secrets. Read-only tests also do not prevent generated Python from manipulating pytest in-process; test success is not proof that hostile code is correct.

## API Budget

AutoDev uses a conservative budget guard before each model call. It does not calculate provider billing from live token prices. Instead, it multiplies the configured estimated cost per model call by the number of reserved calls and stops before exceeding `AUTODEV_API_BUDGET_USD`.

This guard also bounds Codex calls, but the USD estimates do not represent ChatGPT billing or usage limits. The default workflow remains sequential. Parallel mode additionally bounds concurrent developers, task count, total model calls, correction rounds, and operation deadlines.

## CI

GitHub Actions installs the package with development dependencies, runs Ruff, and runs deterministic unit tests. Tests use fake model clients and fake sandbox backends, so no OpenAI API key is required.

A separate Linux CI job builds the pinned sandbox image and runs its dependency preflight using the same non-root, read-only, network-disabled resource restrictions. It mounts no checkout or credential paths and requires no model login or API key.

## Parallel Development

`TaskPlanner` calls the Codex provider with a Pydantic `TaskPlan` schema. Each `DevelopmentTask` includes an ID, exact `owned_files`, a description, and acceptance criteria. Plans reject duplicate IDs, Windows-equivalent path overlap, traversal, nonportable filenames, tests/control files, and more than the configured task count. This initial workflow supports independent Python implementation tasks, not dependency scheduling. A saved plan receives the same validation.

`IntegrationManager` verifies a clean tracked source checkout and captures its branch/HEAD. It rejects credential paths, symlinks, and submodules before checking out anything. It creates an integration branch/worktree and a distinct task branch/worktree per task under a fresh run directory. Untracked source files are not copied. Trusted seeded tests are committed only on the integration branch, without overwriting existing tests. All branches start from the captured source commit.

`ParallelOrchestrator` uses `asyncio.TaskGroup` and a queue of one or two developer slots. Each task has its own provider bound to its worktree. Calls receive the agreed interfaces, ownership, criteria, fixed tests, and read-only context. The Workspace checks the whole output batch before writing and requires every owned file exactly once. Git checks both tracked/untracked changes and the staging index before committing only explicit owned paths. Hooks and filesystem monitors are disabled; branch names, paths, and commands are generated by AutoDev, not executed from model instructions.

After every selected developer completes, IntegrationManager cherry-picks the new commits in plan order into the integration worktree. An agent failure prevents integration of that batch. A conflict stops the workflow and records conflicted paths; there is no automatic conflict resolution, reset, abort, branch deletion, or source-branch merge. Completed worktrees remain available for inspection.

`SandboxChecks` first runs the trusted image preflight through the same restricted container runner. Python isolated mode keeps workspace code out of the preflight import path. It verifies installed runtime/dev distributions against image metadata and the integrated project's declarations/version constraints, and checks pytest/Ruff/Pydantic/dotenv modules. Missing/incompatible dependencies or a stale image without the preflight script stop validation before tests or lint run.

Both pytest and Ruff then validate the integrated tree. `TestRunResult.failure_kind` separates infrastructure failures from code failures; `IntegratedChecks` retains the preflight result. Docker startup/executable/resource/cleanup errors, missing installed tooling/dependencies, and tool configuration/internal errors stop with `infrastructure_failed`. No developer corrections or review are requested. Sequential mode likewise stops without corrections/review for classified infrastructure failures. Dry-run/skipped checks prevent success.

Only genuine code failures are routed by owned implementation paths; ambiguous or test-only errors are sent to all candidate owners. Missing generated local modules remain code failures, so omitted/broken implementations can be corrected. Correction calls see the integrated context but write only their own worktree scope. Their incremental commits are cherry-picked over the preceding integrated version. There are at most three correction rounds after the initial attempt, also constrained by shared budgets and deadlines. Final review runs only after both checks pass; rejection leaves success false.

`ParallelWorkflowReport` records the plan, task/worktree/branch assignments, developer/planner/reviewer timings, task and integration commits, check rounds, corrections, review, conflicts, model-call reservations, and stopped reason. It is printed and saved in the run directory; failure exits nonzero. Agent, provider, Git, and overall deadlines cancel/reap children. Docker's existing per-command timeout bounds checks already running in the executor. Rate limits and malformed/incomplete responses fail safely without provider switching or automatic retries.

Git worktrees share repository metadata; they do not isolate permissions. Codex's read-only policy and AutoDev's scope validation enforce the write boundary, while Docker controls execution. No setting enables a writable Codex sandbox, host execution fallback, or automatic permission escalation. A host that denies Git metadata/worktree writes or Docker must grant explicit permission before the workflow can proceed.

Git clean/smudge filters and custom/union merge drivers are rejected through attribute inspection before baseline checkout or staging new task/seed files, so configuration cannot silently introduce host commands or suppress conflicts. Workflow diffs disable external diff helpers and text conversion. Existing line-ending settings are preserved for Windows compatibility.

Offline tests cover overlap using a two-party barrier, worker limits, ownership enforcement, failure routing, correction caps, deadlines, report persistence, and review gating. Real Git tests in temporary repositories verify branch/worktree isolation, incremental integration, retained conflicts, protected tests, hooks, and unchanged source HEAD. A combined test exercises parallel mock models, real Git integration, and correction. Live Codex throughput and Docker kernel isolation are separate runtime checks and are not inferred from mocks.
# v0.3 local dashboard

`src/autodev/web/` is an optional FastAPI adapter; `frontend/` is a separate Vite React/TypeScript
application. The API calls `build_parallel_orchestrator` with the existing configuration,
`codex_cli` provider, Docker checks and existing limits. It does not implement another agent loop.
The sequential CLI is unchanged. FastAPI/Uvicorn and HTTP test dependencies are optional extras,
so the locked sandbox runtime/development dependency set stays unchanged.

```text
React UI → localhost Vite /api proxy → FastAPI RunService
                                      ↓ asyncio task (one active run)
                               ParallelOrchestrator
                          Planner → scoped Developers (≤2)
                          → IntegrationManager → SandboxChecks → Reviewer
                                      ↓ lifecycle observer
                       report snapshots + bounded activity events
                                      ↓ SSE revision / polling
                                   React UI
```

The observer reports actual lifecycle transitions and snapshots without affecting workflow outcomes.
Existing Pydantic reports remain the disk format. The web adapter adds derived check `passed`
properties only to API snapshots because v0.2 properties are not serialized. Model and validation
failures retain their existing classifications and correction bounds. Planner/reviewer failures now
also mark their attempt as interrupted/failed for accurate presentation.

The service creates ignored per-run metadata before starting work, recovers existing run reports,
and marks previously running metadata interrupted on restart. It does not resume a half-finished
run or clean up its branches. Cancellation propagates through asyncio TaskGroups and the existing
Codex/Git subprocess cancellation handling. Blocking sandbox checks are shielded until their
existing timeout/cleanup finishes, preventing another workflow from starting while Docker cleanup
is still pending. Cancellation before the background coroutine starts is finalized by a task callback.

Security boundaries: only explicit startup repository IDs are accepted in requests, unknown fields
are rejected, limits are bounded, and UI input cannot select executables, provider, network permissions,
Docker options or arbitrary file paths. The entry point accepts loopback binding only. Middleware
requires a loopback peer, valid localhost Host and browser Origin, with a session cookie and CSRF
header for mutations. No wildcard CORS or merge/push endpoints are provided. SSE uses the same
session and emits revision notifications; full details come from authenticated GET requests.

Generated previews resolve only task-owned Python paths below the canonical run integration
directory, independently of absolute paths stored in reports. Traversal and symlink/junction paths
are rejected. Common secret patterns are redacted in API output and UI metadata, and raw Codex
streams are not exposed. No authentication token file is read by dashboard code. Docker security
flags, dependency preflight, fixed commands, scope validation and Git integration policy are reused.

Offline tests cover API validation/security, actual Git lifecycle/report/file behavior, cancellation,
restart recovery and bounded sandbox cleanup. Playwright runs a real browser against a **test-only**
server injecting mock provider/checks into the real orchestrator. It asserts both modules, commits,
report success and overlapping developer attempt intervals; it does not claim a live ChatGPT or
Docker validation occurred. See README for Windows startup and real-demo commands.
