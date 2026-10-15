import { useCallback, useEffect, useRef, useState } from "react";
import { api, session } from "./api";
import type {
  Attempt,
  Check,
  Project,
  Report,
  Run,
  Settings,
  Start,
} from "./types";

const active = (run?: Run) =>
  !!run && ["running", "cancelling"].includes(run.status);
const time = (value?: string) =>
  value
    ? new Date(value).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";
const words = (value: string) => value.replaceAll("_", " ");
export function Badge({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{words(value)}</span>;
}

function Agent({
  name,
  status,
  attempt,
  children,
}: {
  name: string;
  status: string;
  attempt?: Attempt;
  children?: React.ReactNode;
}) {
  return (
    <article className="agent">
      <div className="agent-top">
        <span className={`agent-icon ${status}`}>◈</span>
        <Badge value={status} />
      </div>
      <h3>{name}</h3>
      {children}
      <dl className="agent-times">
        <div>
          <dt>Started</dt>
          <dd>{time(attempt?.started_at)}</dd>
        </div>
        <div>
          <dt>Finished</dt>
          <dd>{time(attempt?.finished_at)}</dd>
        </div>
      </dl>
      {attempt?.duration_seconds ? (
        <small>{attempt.duration_seconds.toFixed(1)} seconds measured</small>
      ) : null}
      {attempt?.error && <p className="error">{attempt.error}</p>}
    </article>
  );
}

function NewTask({
  projects,
  busy,
  onStart,
}: {
  projects: Project[];
  busy: boolean;
  onStart: (request: Start) => Promise<void>;
}) {
  const [form, setForm] = useState<Start>({
    repository_id: projects[0]?.id || "",
    instructions: "",
    concurrency: 2,
    max_tasks: 4,
    max_corrections: 3,
    max_model_calls: 24,
    workflow_timeout_seconds: 1800,
    example: false,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const project = projects.find((p) => p.id === form.repository_id);
  const set = <K extends keyof Start>(name: K, value: Start[K]) =>
    setForm((old) => ({ ...old, [name]: value }));
  return (
    <section className="panel form-panel">
      <div className="section-heading">
        <div>
          <span className="eyebrow">WORKFLOW CONFIGURATION</span>
          <h2>What should your team build?</h2>
        </div>
        <span className="chip">Codex CLI</span>
      </div>
      <p className="muted">
        Describe the outcome and acceptance criteria. AutoDev plans independent
        tasks and validates the integrated result in Docker.
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          setPending(true);
          try {
            await onStart(form);
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setPending(false);
          }
        }}
      >
        <label>
          Repository
          <select
            required
            value={form.repository_id}
            onChange={(e) => set("repository_id", e.target.value)}
          >
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.name} · {p.branch}
              </option>
            ))}
          </select>
        </label>
        <p className="field-hint mono">{project?.path}</p>
        {project?.dirty && (
          <p className="notice">
            This repository has tracked changes. Commit your work manually
            before a real run; AutoDev requires a clean source checkout.
          </p>
        )}
        <label>
          Task instructions
          <textarea
            required
            minLength={8}
            maxLength={20000}
            rows={7}
            placeholder="Describe the Python modules to build, exact behavior, and acceptance criteria…"
            value={form.instructions}
            onChange={(e) => set("instructions", e.target.value)}
          />
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={form.example}
            onChange={(e) => {
              set("example", e.target.checked);
              if (e.target.checked)
                set(
                  "instructions",
                  "Implement the bundled parallel demonstration: arithmetic and text utility modules according to the supplied acceptance tests.",
                );
            }}
          />
          Use the bundled two-module demonstration and trusted acceptance tests
        </label>
        <div className="form-grid">
          {(
            [
              ["concurrency", "Parallel developers", 1, 2],
              ["max_tasks", "Maximum tasks", 1, 8],
              ["max_corrections", "Correction rounds", 0, 3],
              ["max_model_calls", "Model call limit", 3, 48],
              [
                "workflow_timeout_seconds",
                "Workflow timeout (seconds)",
                30,
                3600,
              ],
            ] as const
          ).map(([key, label, min, max]) => (
            <label key={key}>
              {label}
              <input
                type="number"
                required
                min={min}
                max={max}
                step="1"
                value={form[key]}
                onChange={(e) => set(key, Number(e.target.value))}
              />
            </label>
          ))}
        </div>
        <div className="form-footer">
          <p className="muted">
            Isolated worktrees · no automatic push or merge · existing ChatGPT
            login
          </p>
          <button
            className="primary"
            disabled={busy || pending || !projects.length}
          >
            {pending
              ? "Starting…"
              : busy
                ? "Workflow already active"
                : "Start workflow ↗"}
          </button>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </form>
    </section>
  );
}

function CheckOutput({ name, check }: { name: string; check: Check }) {
  return (
    <details className="log-block" open={!check.passed}>
      <summary>
        <span>{name}</span>
        <Badge
          value={check.skipped ? "skipped" : check.passed ? "passed" : "failed"}
        />
      </summary>
      <pre>
        {[
          check.command?.join(" "),
          check.reason,
          check.failure_kind && `Failure class: ${check.failure_kind}`,
          check.timed_out && "Execution timed out",
          check.stdout,
          check.stderr,
        ]
          .filter(Boolean)
          .join("\n\n") || "No output captured."}
      </pre>
    </details>
  );
}

function RunDetail({ run, cancel }: { run: Run; cancel: () => Promise<void> }) {
  const report = run.report;
  const [files, setFiles] = useState<{ id: string; path: string }[]>([]);
  const [preview, setPreview] = useState<{ path: string; text: string } | null>(
    null,
  );
  const [error, setError] = useState("");
  useEffect(() => {
    setPreview(null);
    setError("");
    api<{ id: string; path: string }[]>(`/runs/${run.id}/files`)
      .then(setFiles)
      .catch(() => setFiles([]));
  }, [run.id, run.status]);
  const stages = [
    "integrating",
    "commit_integrated",
    "validating",
    "checks_finished",
    "correcting",
  ];
  const agentStatus = (attempt?: Attempt) =>
    !attempt
      ? "waiting"
      : !attempt.finished_at
        ? active(run)
          ? "running"
          : run.status
        : attempt.error
          ? "failed"
          : "completed";
  const checks = report?.rounds.at(-1)?.checks;
  const fixture = checks?.pytest.command[0] === "mock-pytest";
  const integrationStart = run.events?.find((e) =>
    ["integrating", "validating"].includes(e.stage),
  )?.at;
  const integrationEnd = run.events
    ?.filter((e) => e.stage === "checks_finished")
    .at(-1)?.at;
  const integrationAttempt = integrationStart
    ? {
        agent_id: "integration",
        started_at: integrationStart,
        finished_at: integrationEnd || (!active(run) ? run.finished_at : ""),
        duration_seconds: integrationEnd
          ? (Date.parse(integrationEnd) - Date.parse(integrationStart)) / 1000
          : 0,
      }
    : undefined;
  const tasks = report?.tasks || [];
  const completed = tasks.filter((t) =>
    ["completed", "integrated"].includes(t.status),
  ).length;
  return (
    <>
      <section className="panel run-heading">
        <div>
          <div className="eyebrow">RUN {run.run_id}</div>
          <h2>{words(run.stage)}</h2>
          <p className="run-instructions">{run.instructions}</p>
        </div>
        <div className="run-actions">
          <Badge value={run.status} />
          {active(run) && (
            <button
              className="danger"
              disabled={run.status === "cancelling"}
              onClick={async () => {
                try {
                  await cancel();
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              {run.status === "cancelling"
                ? "Waiting for cleanup…"
                : "Cancel workflow"}
            </button>
          )}
          {report && (
            <a className="button" href={`/api/runs/${run.id}/report`} download>
              ↓ JSON report
            </a>
          )}
        </div>
      </section>
      {run.status === "cancelling" && (
        <p className="notice">
          Cancellation requested. Waiting for model subprocesses and bounded
          Docker cleanup before another run can start.
        </p>
      )}
      {(run.error || report?.stopped_reason || error) && (
        <p
          className={run.status === "succeeded" ? "notice" : "error"}
          role="status"
        >
          {error || run.error || report?.stopped_reason}
        </p>
      )}
      <div className="stats">
        <Stat
          label="Tasks completed"
          value={`${completed} / ${tasks.length || "—"}`}
          detail="Measured task outcomes"
        />
        <Stat
          label="Workflow stage"
          value={words(run.stage)}
          detail={`Started ${time(run.started_at)}`}
        />
        <Stat
          label="Validation"
          value={
            checks
              ? checks.pytest.skipped || checks.ruff.skipped
                ? "Unavailable"
                : checks.pytest.passed && checks.ruff.passed
                  ? "Passed"
                  : "Failed"
              : "Pending"
          }
          detail={
            fixture
              ? "Mock checks · offline test fixture"
              : "Actual Docker pytest + Ruff"
          }
        />
        <Stat
          label="Elapsed"
          value={
            report?.duration_seconds
              ? `${report.duration_seconds.toFixed(1)}s`
              : active(run)
                ? "In progress"
                : "Unavailable"
          }
          detail={
            run.finished_at
              ? `Finished ${time(run.finished_at)}`
              : "Final duration recorded at completion"
          }
        />
      </div>
      <section>
        <div className="section-heading">
          <h2>Agent workspace</h2>
          <span className="muted">
            Actual execution status · no estimated percentages
          </span>
        </div>
        <div className="agents">
          <Agent
            name="Planner"
            status={
              report?.plan && !report.planner_execution
                ? "supplied_plan"
                : agentStatus(report?.planner_execution)
            }
            attempt={report?.planner_execution}
          >
            <p>
              {report?.plan?.summary ||
                "Decomposes the request into independent tasks."}
            </p>
          </Agent>
          {tasks.map((task) => (
            <Agent
              key={task.task.id}
              name={
                task.attempts
                  .at(-1)
                  ?.agent_id.replace("developer-", "Developer ") ||
                "Developer · queued"
              }
              status={task.status}
              attempt={task.attempts.at(-1)}
            >
              <strong className="task-id">{task.task.id}</strong>
              <p>{task.task.description}</p>
              <div className="file-tags">
                {task.task.owned_files.map((p) => (
                  <code key={p}>{p}</code>
                ))}
              </div>
              <details>
                <summary>Acceptance criteria</summary>
                <ul>
                  {task.task.acceptance_criteria.map((c) => (
                    <li key={c}>{c}</li>
                  ))}
                </ul>
              </details>
              {task.attempts.at(-1)?.commit && (
                <code className="commit">
                  {task.attempts.at(-1)?.commit?.slice(0, 12)}
                </code>
              )}
            </Agent>
          ))}
          {!tasks.length &&
            [1, 2].map((n) => (
              <Agent key={n} name={`Developer ${n}`} status="waiting">
                <p>Waiting for a scoped task assignment.</p>
              </Agent>
            ))}
          <Agent
            name="Integration"
            attempt={integrationAttempt}
            status={
              stages.includes(run.stage) && active(run)
                ? "running"
                : checks
                  ? checks.pytest.passed && checks.ruff.passed
                    ? "completed"
                    : "failed"
                  : "waiting"
            }
          >
            <p>
              Collects commits in a temporary branch and runs isolated checks.
            </p>
          </Agent>
          <Agent
            name="Reviewer"
            status={agentStatus(report?.reviewer_execution)}
            attempt={report?.reviewer_execution}
          >
            <p>
              {report?.review?.summary ||
                "Reviews the validated integration result."}
            </p>
          </Agent>
        </div>
      </section>
      <div className="detail-grid">
        <section className="panel">
          <div className="section-heading">
            <h2>Validation & feedback</h2>
            <span className="chip">
              {fixture ? "Offline test fixture" : "Docker sandbox"}
            </span>
          </div>
          {!checks && (
            <div className="empty compact">
              Validation output appears when checks finish.
            </div>
          )}
          {report?.rounds.map(
            (round) =>
              round.checks && (
                <div key={round.number}>
                  <h3>
                    {round.number === 0
                      ? "Initial validation"
                      : `Correction ${round.number}`}
                  </h3>
                  {round.checks.environment && (
                    <CheckOutput
                      name="Environment"
                      check={round.checks.environment}
                    />
                  )}
                  <CheckOutput name="pytest" check={round.checks.pytest} />
                  <CheckOutput name="Ruff" check={round.checks.ruff} />
                </div>
              ),
          )}
          {report?.review && (
            <div className="review">
              <h3>
                Reviewer feedback{" "}
                <Badge
                  value={
                    report.review.approved ? "approved" : "changes_requested"
                  }
                />
              </h3>
              <p>{report.review.summary}</p>
              {report.review.findings?.length > 0 && (
                <pre>{JSON.stringify(report.review.findings, null, 2)}</pre>
              )}
            </div>
          )}
        </section>
        <section className="panel">
          <div className="section-heading">
            <h2>Activity</h2>
            <span className="live-dot" />
          </div>
          <div className="events">
            {run.events?.length ? (
              [...run.events].reverse().map((event, i) => (
                <div className="event" key={i}>
                  <time>{time(event.at)}</time>
                  <div>
                    <strong>{words(event.stage)}</strong>
                    {event.task_id && <small>{event.task_id}</small>}
                    {event.error && <p className="error">{event.error}</p>}
                  </div>
                </div>
              ))
            ) : (
              <p className="muted">
                Historical reports may not include a live event log.
              </p>
            )}
          </div>
        </section>
      </div>
      <section className="panel">
        <div className="section-heading">
          <h2>Integration & generated files</h2>
          <span className="chip">Retained for your review</span>
        </div>
        <dl className="git-details">
          <div>
            <dt>Integration branch</dt>
            <dd>
              <code>
                {report?.integration_branch || "Awaiting preparation"}
              </code>
            </dd>
          </div>
          <div>
            <dt>Integration commit</dt>
            <dd>
              <code>{report?.integration_commit || "—"}</code>
            </dd>
          </div>
          <div>
            <dt>Source branch</dt>
            <dd>{report?.source_branch || "—"}</dd>
          </div>
        </dl>
        <p className="muted">
          AutoDev never pushes or merges into your source branch. Review the
          integration worktree before making manual Git changes.
        </p>
        <div className="file-tags">
          {files.map((file) => (
            <button
              key={file.id}
              onClick={async () => {
                try {
                  const response = await fetch(
                    `/api/runs/${run.id}/files/${file.id}`,
                  );
                  if (!response.ok)
                    throw new Error("Generated file unavailable");
                  setPreview({ path: file.path, text: await response.text() });
                } catch (err) {
                  setError((err as Error).message);
                }
              }}
            >
              {file.path} ↗
            </button>
          ))}
        </div>
        {preview && (
          <div className="file-preview">
            <div className="section-heading">
              <h3>{preview.path}</h3>
              <button onClick={() => setPreview(null)}>Close preview</button>
            </div>
            <pre>{preview.text}</pre>
          </div>
        )}
      </section>
    </>
  );
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="stat">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState("Dashboard");
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<Run>();
  const selectedId = useRef("");
  const [settings, setSettings] = useState<Settings>();
  const [connection, setConnection] = useState("Connecting");
  const [error, setError] = useState("");
  const refresh = useCallback(async () => {
    try {
      const [history, repositories] = await Promise.all([
        api<Run[]>("/runs"),
        api<Project[]>("/projects"),
      ]);
      setRuns(history);
      setProjects(repositories);
      const id = selectedId.current || history[0]?.id;
      if (id) {
        const detail = await api<Run>(`/runs/${id}`);
        if (!selectedId.current || selectedId.current === id) {
          selectedId.current = id;
          setSelected(detail);
        }
      }
      setError("");
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    let closed = false;
    let events: EventSource | undefined;
    let timer: ReturnType<typeof setInterval>;
    session()
      .then(async () => {
        if (closed) return;
        setSettings(await api<Settings>("/settings"));
        await refresh();
        if (closed) return;
        timer = setInterval(refresh, 3000);
        if (typeof EventSource !== "undefined") {
          events = new EventSource("/api/events");
          events.onopen = () => setConnection("Live updates");
          events.onmessage = () => void refresh();
          events.onerror = () => setConnection("Polling fallback");
        } else setConnection("Polling fallback");
      })
      .catch((err) => {
        if (!closed) {
          setConnection("Disconnected");
          setError((err as Error).message);
        }
      });
    return () => {
      closed = true;
      clearInterval(timer);
      events?.close();
    };
  }, [refresh]);
  const choose = async (run: Run) => {
    try {
      selectedId.current = run.id;
      setSelected(await api<Run>(`/runs/${run.id}`));
      setPage("Dashboard");
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const running = runs.find(active);
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Dashboard");
          }}
        >
          <span className="brand-mark">
            A<span>↗</span>
          </span>
          <div>
            AutoDev<small>DEVELOPMENT CONTROL ROOM</small>
          </div>
        </a>
        <div className="workspace-label">
          WORKSPACE <span>LOCAL</span>
        </div>
        <nav aria-label="Main navigation">
          {[
            ["Dashboard", "▦"],
            ["New Task", "＋"],
            ["Runs", "◷"],
            ["Settings", "⚙"],
          ].map(([name, icon]) => (
            <button
              key={name}
              aria-label={name}
              className={page === name ? "selected" : ""}
              onClick={() => setPage(name)}
            >
              <span aria-hidden="true">{icon}</span>
              {name}
              {name === "Runs" && <small>{runs.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span className="provider-dot" />
          Codex CLI <Badge value="configured" />
          <p>
            Uses your existing ChatGPT login.
            <br />
            Authentication is checked when a run starts.
          </p>
          <div className="version">
            AUTODEV v0.3 <span>LOCAL ONLY</span>
          </div>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span> {page}
          </span>
          <div>
            <span className="live-dot" />
            {connection}
            <span className="avatar">AD</span>
          </div>
        </header>
        <div className="content">
          <div className="page-title">
            <div>
              <span className="eyebrow">AUTONOMOUS DEVELOPMENT</span>
              <h1>
                {page === "Dashboard"
                  ? "Your development control room"
                  : page === "New Task"
                    ? "Start a new task"
                    : page === "Runs"
                      ? "Run history"
                      : "Workspace settings"}
              </h1>
              <p className="muted">
                {page === "Dashboard"
                  ? "Plan, build, integrate, and review — with every step in view."
                  : "Local workflows. Isolated execution. You stay in control."}
              </p>
            </div>
            {page !== "New Task" && (
              <button className="primary" onClick={() => setPage("New Task")}>
                ＋ New task
              </button>
            )}
          </div>
          {error && (
            <p role="alert" className="error">
              {error} Start the backend on localhost and reload to reconnect.
            </p>
          )}
          {page === "New Task" &&
            (projects.length ? (
              <NewTask
                projects={projects}
                busy={!!running}
                onStart={async (request) => {
                  const run = await api<Run>("/runs", request);
                  selectedId.current = run.id;
                  setSelected(run);
                  setPage("Dashboard");
                  await refresh();
                }}
              />
            ) : (
              <div className="empty panel">
                Connect to the backend to load your registered repositories.
              </div>
            ))}
          {page === "Dashboard" && (
            <>
              {projects[0] && (
                <div className="project-strip">
                  <span className="project-symbol">⌘</span>
                  <div>
                    <strong>
                      {projects.find((p) => p.id === selected?.repository_id)
                        ?.name || projects[0].name}
                    </strong>
                    <small className="mono">
                      {projects.find((p) => p.id === selected?.repository_id)
                        ?.path || projects[0].path}
                    </small>
                  </div>
                  <span className="chip">
                    ⑂{" "}
                    {projects.find((p) => p.id === selected?.repository_id)
                      ?.branch || projects[0].branch}
                  </span>
                  <span className="local-label">Local repository</span>
                </div>
              )}
              {selected ? (
                <RunDetail
                  run={selected}
                  cancel={async () => {
                    setSelected(
                      await api<Run>(`/runs/${selected.id}/cancel`, {}),
                    );
                    await refresh();
                  }}
                />
              ) : (
                <>
                  <div className="stats">
                    <Stat
                      label="Current workflow"
                      value="Ready"
                      detail="No execution has started"
                    />
                    <Stat
                      label="Parallel developers"
                      value="Up to 2"
                      detail="Isolated Git worktrees"
                    />
                    <Stat
                      label="Validation"
                      value="Docker"
                      detail="Offline runtime sandbox"
                    />
                    <Stat
                      label="Previous runs"
                      value={String(runs.length)}
                      detail="From local report files"
                    />
                  </div>
                  <section className="panel empty">
                    <span className="empty-icon">⌘</span>
                    <h2>Your next build starts here</h2>
                    <p>
                      Give AutoDev a scoped task. Watch the agents work,
                      <br />
                      inspect validation output, and review the integrated code.
                    </p>
                    <button
                      className="primary"
                      onClick={() => setPage("New Task")}
                    >
                      Create your first task ↗
                    </button>
                    <small>
                      Real Codex execution · ChatGPT authentication · no API key
                    </small>
                  </section>
                </>
              )}
              {runs.length > 0 && (
                <section className="panel">
                  <div className="section-heading">
                    <h2>Recent runs</h2>
                    <button onClick={() => setPage("Runs")}>View all →</button>
                  </div>
                  <History runs={runs.slice(0, 5)} choose={choose} />
                </section>
              )}
            </>
          )}
          {page === "Runs" && (
            <section className="panel">
              <div className="section-heading">
                <h2>Local execution history</h2>
                <span className="chip">{runs.length} runs</span>
              </div>
              <History runs={runs} choose={choose} />
            </section>
          )}
          {page === "Settings" && (
            <section className="panel">
              <div className="section-heading">
                <h2>Safe by default</h2>
                <Badge value="local" />
              </div>
              {settings ? (
                <dl className="settings">
                  {Object.entries(settings).map(([key, value]) => (
                    <div key={key}>
                      <dt>{words(key)}</dt>
                      <dd>{String(value)}</dd>
                    </div>
                  ))}
                </dl>
              ) : (
                <p>Loading settings…</p>
              )}
              <h3>Registered repositories</h3>
              {projects.map((p) => (
                <div className="repository-setting" key={p.id}>
                  <strong>{p.name}</strong>
                  <code>{p.path}</code>
                  <Badge value={p.dirty ? "uncommitted_changes" : "clean"} />
                </div>
              ))}
              <p className="muted">
                Repository access is configured with backend <code>--repo</code>{" "}
                arguments. Restart the backend to change the allowlist. Browser
                inputs cannot expand filesystem or execution permissions.
              </p>
            </section>
          )}
          <footer>
            AutoDev <span>Local workspace. No automatic push or merge.</span>
            <span>v0.3.0</span>
          </footer>
        </div>
      </main>
    </div>
  );
}

function History({
  runs,
  choose,
}: {
  runs: Run[];
  choose: (run: Run) => Promise<void>;
}) {
  return runs.length ? (
    <div className="history">
      {runs.map((run) => (
        <button
          className="history-row"
          key={run.id}
          onClick={() => void choose(run)}
        >
          <span className="history-icon">↗</span>
          <div>
            <strong>{run.instructions}</strong>
            <small>
              {run.run_id} · {new Date(run.started_at).toLocaleString()}
            </small>
          </div>
          <Badge value={run.status} />
          <span>→</span>
        </button>
      ))}
    </div>
  ) : (
    <div className="empty compact">
      No report files yet. Completed and interrupted runs will appear here.
    </div>
  );
}
