# AutoDev Architecture

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

The fixed pytest command remains unchanged. Container environment settings disable bytecode writes, pytest's cache, and third-party plugin autoloading so standard tests run against the read-only workspace. Tests that need temporary files must use `/tmp`, such as through pytest's `tmp_path` fixture.

Each container receives a unique name. AutoDev kills the Docker CLI on timeout and attempts `docker rm --force` in a `finally` block, including when the caller is interrupted. Cleanup failure disables success; investigate the reported container before resuming execution. Python retains a bounded prefix of stdout and stderr while draining the pipes, and Docker does not persist container logs.

Build the default runtime image with `docker build -f docker/sandbox/Dockerfile -t autodev-sandbox:py311 .`. The image contains Python 3.11, pytest, Ruff, Pydantic, and dotenv; runtime network access stays disabled. Parallel checks use the same container restrictions and cleanup for both fixed pytest and Ruff commands. Ruff ignores repository configuration (`--isolated`), disables caching, and uses AutoDev's explicit lint rules. Git-specific offline tests skip if Git is absent from the image.

If Docker is unavailable, execution is skipped. Do not treat this as a complete sandbox for hostile code without additional host hardening.

The regression tests inspect Docker arguments and mock container lifecycle calls. They do not verify kernel isolation, network denial, or resource enforcement. A live Docker daemon was unavailable during this review, so these runtime properties remain unverified. Use only a trusted local Linux image and a dedicated workspace without secrets. Read-only tests also do not prevent generated Python from manipulating pytest in-process; test success is not proof that hostile code is correct.

## API Budget

AutoDev uses a conservative budget guard before each model call. It does not calculate provider billing from live token prices. Instead, it multiplies the configured estimated cost per model call by the number of reserved calls and stops before exceeding `AUTODEV_API_BUDGET_USD`.

This guard also bounds Codex calls, but the USD estimates do not represent ChatGPT billing or usage limits. The default workflow remains sequential. Parallel mode additionally bounds concurrent developers, task count, total model calls, correction rounds, and operation deadlines.

## CI

GitHub Actions installs the package with development dependencies, runs Ruff, and runs deterministic unit tests. Tests use fake model clients and fake sandbox backends, so no OpenAI API key is required.

## Parallel Development

`TaskPlanner` calls the Codex provider with a Pydantic `TaskPlan` schema. Each `DevelopmentTask` includes an ID, exact `owned_files`, a description, and acceptance criteria. Plans reject duplicate IDs, Windows-equivalent path overlap, traversal, nonportable filenames, tests/control files, and more than the configured task count. This initial workflow supports independent Python implementation tasks, not dependency scheduling. A saved plan receives the same validation.

`IntegrationManager` verifies a clean tracked source checkout and captures its branch/HEAD. It rejects credential paths, symlinks, and submodules before checking out anything. It creates an integration branch/worktree and a distinct task branch/worktree per task under a fresh run directory. Untracked source files are not copied. Trusted seeded tests are committed only on the integration branch, without overwriting existing tests. All branches start from the captured source commit.

`ParallelOrchestrator` uses `asyncio.TaskGroup` and a queue of one or two developer slots. Each task has its own provider bound to its worktree. Calls receive the agreed interfaces, ownership, criteria, fixed tests, and read-only context. The Workspace checks the whole output batch before writing and requires every owned file exactly once. Git checks both tracked/untracked changes and the staging index before committing only explicit owned paths. Hooks and filesystem monitors are disabled; branch names, paths, and commands are generated by AutoDev, not executed from model instructions.

After every selected developer completes, IntegrationManager cherry-picks the new commits in plan order into the integration worktree. An agent failure prevents integration of that batch. A conflict stops the workflow and records conflicted paths; there is no automatic conflict resolution, reset, abort, branch deletion, or source-branch merge. Completed worktrees remain available for inspection.

Both pytest and Ruff validate the integrated tree through `SandboxChecks`. A skipped check prevents success. Failed checks are routed by owned implementation paths; ambiguous or test-only errors are sent to all candidate owners. Correction calls see the integrated context but write only their own worktree scope. Their incremental commits are cherry-picked over the preceding integrated version. There are at most three correction rounds after the initial attempt, also constrained by shared budgets and deadlines. Final review runs only after both checks pass; rejection leaves success false.

`ParallelWorkflowReport` records the plan, task/worktree/branch assignments, developer/planner/reviewer timings, task and integration commits, check rounds, corrections, review, conflicts, model-call reservations, and stopped reason. It is printed and saved in the run directory; failure exits nonzero. Agent, provider, Git, and overall deadlines cancel/reap children. Docker's existing per-command timeout bounds checks already running in the executor. Rate limits and malformed/incomplete responses fail safely without provider switching or automatic retries.

Git worktrees share repository metadata; they do not isolate permissions. Codex's read-only policy and AutoDev's scope validation enforce the write boundary, while Docker controls execution. No setting enables a writable Codex sandbox, host execution fallback, or automatic permission escalation. A host that denies Git metadata/worktree writes or Docker must grant explicit permission before the workflow can proceed.

Git clean/smudge filters and custom/union merge drivers are rejected through attribute inspection before baseline checkout or staging new task/seed files, so configuration cannot silently introduce host commands or suppress conflicts. Workflow diffs disable external diff helpers and text conversion. Existing line-ending settings are preserved for Windows compatibility.

Offline tests cover overlap using a two-party barrier, worker limits, ownership enforcement, failure routing, correction caps, deadlines, report persistence, and review gating. Real Git tests in temporary repositories verify branch/worktree isolation, incremental integration, retained conflicts, protected tests, hooks, and unchanged source HEAD. A combined test exercises parallel mock models, real Git integration, and correction. Live Codex throughput and Docker kernel isolation are separate runtime checks and are not inferred from mocks.
