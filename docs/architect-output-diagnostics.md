# Project Architect structured-output diagnosis

## Incident: a9deecafaa1b

The retained invoice demonstration report records one architect call, no specification,
no developers, no checkpoints, and `Codex CLI returned invalid JSON for ProjectSpec.`
The original provider did not retain its response, so the exact rejected value from that
particular call cannot be recovered. Existing runs and trusted acceptance tests were
left unchanged during this investigation.

A read-only reproduction with the original provider returned **valid JSON** (10,530
bytes). Pydantic rejected `milestones[3].test_paths` with the application rule
`Unsafe or nonportable project path`. The original catch-all handler incorrectly
described every Pydantic validation error as invalid JSON. The rejected path itself
was not printed or saved.

The advertised JSON schema had described test paths as unrestricted strings, while
application validators required exact, portable, existing `tests/*.py` file paths.
Structured output could therefore satisfy the advertised schema and still fail the
application contract. Repository/ownership path constraints were also absent from
the transport schema. The architect prompt compounded this mismatch by including
developer instructions to return source files.

## Supported transport and fix

Installed Codex CLI `0.162.0-alpha.17.2` advertises `exec --output-schema`. The
[official non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
documents a final message on stdout and progress on stderr; `--json` separately
selects a JSONL event stream. AutoDev uses the supported final-message contract,
without `--json`. Switching to event extraction or markdown stripping is unnecessary.

- ProjectSpec now advertises portable path patterns, exact Python test-file syntax,
  the actual ten-file ownership limit, and descriptions for component/task/milestone
  relationships. Existing runtime safety validators still enforce reserved paths,
  protected ownership, DAG consistency, and trusted-baseline test membership.
- The architect receives a dedicated specification prompt with the exact available
  trusted test paths. It no longer receives developer source-generation instructions.
- `ProviderJSONParseError` identifies malformed JSON/encoding and gives line/column
  where available. `ProviderSchemaError` identifies valid JSON rejected by field or
  project-consistency validation, with bounded field locations and safe rule codes.
  Both remain subclasses of `ProviderResponseError` for existing callers.
- Neither diagnostic includes raw response text, field values, arbitrary extra keys,
  validation exception text, or raw stderr. The project report preserves the safe
  diagnostic in both `stopped_reason` and `planner_execution.error`.

There are no hidden retries. Architecture failure stops before developers and reserves
one model call. Review the diagnostic before explicitly starting a new run; repeated
model calls cannot guarantee project invariants. Existing timeout/output/call limits,
ChatGPT-only authentication, read-only Codex execution, Git isolation, Docker
restrictions and checkpoint serialization remain unchanged.

## Retrying the demonstration

Restart the dashboard backend so it loads the updated provider and schema, then
submit the invoice request as a **new project run** using the existing repository and
trusted tests. Do not force-resume `a9deecafaa1b`: it has no validated architecture
checkpoint. Its retained report and integration worktree remain available for inspection.
No API key or new authentication setup is required. Rebuilding the Docker test image
is unnecessary for this provider-only change; a containerized backend must load the
updated source through its normal rebuild/restart process.

## Verification

`tests/test_architect_output.py` covers valid ProjectSpec output, malformed/empty/
non-UTF-8/fenced/JSONL responses, schema and dependency failures, redacted diagnostics,
advertised path constraints, the CLI stdout/stderr contract, and failure propagation
through real temporary Git integration worktrees. All model responses in these tests
are mocked. Existing milestone, concurrency, checkpoint, Docker and dashboard tests
remain part of the full suite. See the delivery report for actual command results.

Local Windows/Python 3.12 verification:

- `python -m ruff check .`: passed.
- Full `python -m pytest --basetemp <fresh Windows TEMP directory> -p no:cacheprovider
  --tb=short -rs`: **273 passed, 2 skipped**, 165.53 seconds. Both skips require
  unavailable Windows symlink support.
- Frontend `npm test`: **8 passed**; `npm run typecheck` and `npm run build`: passed.
- Playwright: **2 passed**, 29.4 seconds, including multi-stage pause/resume. Initial
  attempts encountered the occupied IPv4 dashboard port, a temporary-configuration
  working-directory timeout, and the existing origin policy rejecting port 5174
  (two browser failures). The final passing run used a temporary, ignored configuration
  bound to IPv6 localhost on port 5173, which the existing origin policy permits.
  No security rules or tracked browser tests were changed.

A subsequent live, read-only architect-only call with the corrected schema passed
ProjectSpec and trusted-baseline validation: four tasks and four milestones. It used
the existing ChatGPT login and did not launch developers, execute generated code,
or modify the original failed run. This verifies architecture planning, not completion
of the entire invoice project.
