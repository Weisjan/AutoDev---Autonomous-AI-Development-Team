# Project validation and requested milestones

## Incident 190f23d78eed

The retained report contains a validated architecture but four milestones instead of the
requested three. Domain and formatting were placed in separate milestones despite having
no dependency between them. The architect prompt had explicitly requested **four ordered
milestones**, overriding the invoice request's Core / Application / Documentation structure.
The scheduler correctly honored those supplied barriers; the incorrect plan serialized the work.

For each of three domain attempts, trusted pytest passed (2 tests) and whole-repository Ruff
reported `tests/test_domain.py:1:1: I001`. That protected test already existed in the baseline.
Ruff exit 1 was labeled a code failure, and the shared ownership matcher defaulted to all batch
owners when no implementation filename matched. Consequently domain was retried twice even
though it could not modify the offending test. No developers reached subsequent milestones.

The original run, reports, checkpoints and trusted invoice tests remain unchanged. No live
Codex invoice workflow was rerun as part of this fix.

## Validation policy

Project mode now passes an explicit lint scope to the existing Docker sandbox. After each
integrated batch and at final validation, that scope contains **every integrated task-owned
Python file**, including earlier milestones and modified existing implementation files. It
does not include future files that have not been integrated, protected tests or unrelated
baseline source. Non-Python documentation/data files are outside Ruff's Python rule scope.

The rules remain `E,F,I,UP,B,SIM`, target Python 3.11, line length 100, isolated configuration,
no cache and no fixes. Exact safe paths follow an option terminator (`--`); model-selected
commands/options are not accepted. Reports retain the actual command and a scope explanation.
If a project owns no Python files, the report explicitly states no Ruff process was needed;
pytest is still mandatory. This policy does **not** assert the entire baseline is lint-clean.

Pytest selection is unchanged: trusted task tests and prerequisite tests are cumulative,
milestone tests validate milestone completion, and the final complete trusted suite must pass
before review. Protected test assertions are never skipped, rewritten or weakened to fix lint.

| Failure | Result and correction policy |
| --- | --- |
| Missing Docker/dependencies/executable, environment failure | `infrastructure_failed`; no developer correction |
| Unexpected Ruff diagnostic outside integrated task ownership | `failure_kind: baseline`, `baseline_failed`; manual baseline review, no developer correction |
| Ruff failure in current batch-owned implementation | Correct only the matching owner(s), within existing limits |
| Ruff output truncated/unattributed, or failure in a previously validated file outside the current batch | Stop for manual review, no guessed correction owner |
| Functional pytest failure | Existing bounded implementation correction policy; a trusted test filename alone does not make it a baseline lint failure |

Unexpected baseline diagnostics are retained rather than silently accepted. Ordinary project
validation avoids such lint diagnostics through explicit scope. Independent-task mode retains
whole-repository lint, but now also stops for identifiable baseline lint failures instead of
asking unrelated developers to fix protected files. Sequential behavior remains unchanged.

Docker runtime networking, non-root user, read-only mounts/root filesystem, CPU/memory/process
limits, cleanup and timeouts are unchanged. Codex still uses the existing ChatGPT login and
read-only provider. No authentication tokens or paid API are used by this change.

## Requested milestone contract

The architect prompt preserves user-requested milestone names, file groupings and independence;
four is a maximum, not a required count. Before developers start, the architect validates explicit
English count forms such as `Design three milestones` or `Use 3 milestones`. Unsupported or
conflicting counts stop before a model call. Numbered `Name: ...` heading lines constrain recognized
names/order, explicit file ownership groupings and explicitly independent tasks. This is bounded
syntax recognition, not a general natural-language requirements interpreter. Other request styles
still use the prompt and normal structured ProjectSpec/DAG validation. Invalid plans stop safely;
AutoDev does not silently rewrite milestones or introduce extra model calls.

For the bundled invoice request the required schedule is:

1. **Core:** domain.py and formatting.py in separate, independent tasks in the same milestone.
2. **Application:** app.py after both core tasks have been integrated and validated.
3. **Documentation:** README.md after the application has been integrated and validated.

The existing DAG scheduler and asyncio execution remain in use. Tasks receive isolated worktrees
based on the current validated integration commit, and concurrency remains bounded to the configured
one or two developers. Regression tests verify barrier-backed overlap of both core tasks, later
start times after validation, and prerequisite commit identities in dependent worktrees.

No report/checkpoint fields or checksum algorithms changed. The additional failure-kind literal
does not alter serialization of existing checkpoints. Recovery still verifies commit identity,
worktrees, clean state, dependency state and checksum; the new code does not reinterpret or rewrite
old architecture checkpoints. An old four-stage plan stays as recorded. Failed in-flight runs must
not be force-resumed; review retained state and explicitly start a new run after committing this fix.

## Verification

`tests/test_project_validation.py` uses mocked models and pytest results, real disposable Git
worktrees, and real static Ruff checks (no generated fixture code executes on the host). It copies
the existing acceptance tests without editing them and verifies protected Git blob identity.
It reproduces successful domain pytest plus the pre-existing test I001, cumulative lint scope,
baseline/unattributed failures without correction, targeted implementation lint correction,
the exact three-stage schedule, malformed milestone contracts and unsafe lint paths.

A separate, local **Docker-only static fixture** check used the existing sandbox image and real
pytest/Ruff: domain tests **2 passed**, scoped Ruff passed, whole-repository Ruff reproduced the
protected-test I001, then the complete fixture suite **4 passed** with all implementation files
passing scoped Ruff. This check had no agents, no model calls and no access to previous runs.

Restart the backend to load the change. No dependency changes or sandbox image rebuild are
required for scoped command construction; rebuild/restart a containerized backend through its
normal workflow if it packages the application source. Real Codex verification is intentionally
left for the user's review/commit step. The delivery report records the full suite results.

Final Windows / Python 3.12 results:

| Check | Actual result |
| --- | --- |
| Ruff, `python -m ruff check .` | Passed |
| Complete pytest, fresh explicit Windows TEMP directory, cache disabled | **299 passed, 2 skipped**, 188.12 seconds |
| New invoice validation/scheduling regressions | **26 passed** |
| Frontend Vitest | **8 passed** |
| Frontend TypeScript checking and production build | Passed |
| Playwright browser integration tests | **2 passed**, 30.9 seconds |
| Docker-only domain fixture / final complete fixture suite | **2 passed / 4 passed**, scoped Ruff passed |
| Git diff whitespace review | Passed |

Both pytest skips concern symlink creation unavailable on this Windows host. Browser tests used
IPv6 localhost port 5173 through an ignored temporary configuration, leaving the existing IPv4
dashboard untouched and preserving the existing allowed-origin policy. No frontend source or
tracked E2E tests were changed.

Changed source files: `architect.py`, `providers.py`, `project.py`, `parallel.py`, `sandbox.py`,
`schemas.py`, `parallel_schemas.py`, and new `validation.py` under `src/autodev/`. Test changes are
`tests/project_fakes.py` and new `tests/test_project_validation.py`. Documentation changes are
README, architecture documentation and this report. Existing untracked user reports are retained.
