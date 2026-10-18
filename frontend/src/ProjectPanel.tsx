import { useState } from "react";
import { api } from "./api";
import type { Run } from "./types";

export default function ProjectPanel({
  run,
  changed,
}: {
  run: Run;
  changed: (run: Run) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const report = run.report!;
  const spec = report.specification;
  const command = async (action: "pause" | "resume") => {
    setError("");
    setPending(true);
    try {
      changed(
        await api<Run>(
          `/runs/${run.id}/${action}`,
          action === "resume" ? { confirmed } : {},
        ),
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPending(false);
    }
  };
  const validated = new Set(report.validated_tasks || []);
  const statuses = new Map(report.tasks.map((t) => [t.task.id, t.status]));
  const levels = new Map<string, number>();
  function rank(id: string, visiting = new Set<string>()): number {
    if (levels.has(id)) return levels.get(id)!;
    if (visiting.has(id)) return 0;
    const task = spec?.tasks.find((t) => t.id === id);
    const level = task?.depends_on.length
      ? 1 +
        Math.max(
          ...task.depends_on.map((dep) =>
            rank(dep, new Set([...visiting, id])),
          ),
        )
      : 0;
    levels.set(id, level);
    return level;
  }
  const positions = new Map<string, { x: number; y: number }>();
  const rows = new Map<number, number>();
  spec?.tasks.forEach((task) => {
    const level = rank(task.id);
    const row = rows.get(level) || 0;
    rows.set(level, row + 1);
    positions.set(task.id, { x: level * 230 + 15, y: row * 92 + 20 });
  });
  return (
    <section className="panel project-panel" aria-label="Project orchestration">
      <div className="section-heading">
        <div>
          <span className="eyebrow">MULTI-STAGE PROJECT</span>
          <h2>
            {spec?.title || "Architect is preparing the project specification"}
          </h2>
        </div>
        <span className="chip">Python / Docker · Phase 1</span>
      </div>
      <p className="muted">
        {spec?.summary ||
          "Execution waits for a validated architecture and dependency graph."}
      </p>
      <div className="project-controls">
        {run.status === "running" && !report.reviewer_execution && (
          <button disabled={pending} onClick={() => void command("pause")}>
            Pause at next checkpoint
          </button>
        )}
        {run.status === "pausing" && (
          <p className="notice">
            Pause requested. Current integration and validation finish first.
          </p>
        )}
        {["paused", "interrupted"].includes(run.status) && (
          <>
            {report.checkpoint_safe ? (
              <>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  I reviewed the checkpoint; verify repository state before
                  resuming.
                </label>
                <button
                  className="primary"
                  disabled={!confirmed || pending}
                  onClick={() => void command("resume")}
                >
                  Verify and resume project
                </button>
              </>
            ) : (
              <p className="notice">
                Safe recovery cannot be established. Inspect retained worktrees
                and explicitly confirm a new run after manual recovery.
                Force-resume is disabled.
              </p>
            )}
          </>
        )}
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </div>
      {spec && (
        <>
          <div className="section-heading">
            <h3>Milestones</h3>
            <span className="muted">
              {validated.size} / {spec.tasks.length} tasks validated · measured
              outcomes
            </span>
          </div>
          <div className="milestone-grid">
            {spec.milestones.map((milestone) => {
              const measured = report.milestones?.find(
                (m) => m.id === milestone.id,
              );
              return (
                <article className="milestone-card" key={milestone.id}>
                  <div className="section-heading">
                    <h3>{milestone.id}</h3>
                    <span className={`badge ${measured?.status || "pending"}`}>
                      {measured?.status || "pending"}
                    </span>
                  </div>
                  <p>{milestone.description}</p>
                  <ul>
                    {milestone.acceptance_criteria.map((c) => (
                      <li key={c}>{c}</li>
                    ))}
                  </ul>
                  <small>{milestone.task_ids.join(" · ")}</small>
                  <p className="mono">
                    {measured?.started_at
                      ? new Date(measured.started_at).toLocaleTimeString()
                      : "Not started"}{" "}
                    →{" "}
                    {measured?.finished_at
                      ? new Date(measured.finished_at).toLocaleTimeString()
                      : "—"}
                  </p>
                  {measured?.commit && (
                    <code>{measured.commit.slice(0, 12)}</code>
                  )}
                </article>
              );
            })}
          </div>
          <h3>Task dependency graph</h3>
          <p className="muted">
            Arrows show prerequisites. Dependent tasks wait for integrated,
            tested outputs.
          </p>
          <div className="dependency-graph">
            <svg
              role="img"
              aria-label="Task dependency graph"
              viewBox={`0 0 ${Math.max(...[...levels.values()], 0) * 230 + 225} ${Math.max(...[...rows.values()], 1) * 92 + 20}`}
            >
              <defs>
                <marker
                  id="dependency-arrow"
                  viewBox="0 0 10 10"
                  refX="9"
                  refY="5"
                  markerWidth="6"
                  markerHeight="6"
                  orient="auto-start-reverse"
                >
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="#69998b" />
                </marker>
              </defs>
              {spec.tasks.flatMap((task) =>
                task.depends_on.map((dep) => {
                  const a = positions.get(dep),
                    b = positions.get(task.id);
                  return a && b ? (
                    <path
                      key={`${dep}-${task.id}`}
                      d={`M ${a.x + 190} ${a.y + 29} C ${a.x + 215} ${a.y + 29}, ${b.x - 25} ${b.y + 29}, ${b.x} ${b.y + 29}`}
                      fill="none"
                      stroke="#477565"
                      strokeWidth="2"
                      markerEnd="url(#dependency-arrow)"
                    />
                  ) : null;
                }),
              )}
              {spec.tasks.map((task) => {
                const p = positions.get(task.id)!;
                const status = validated.has(task.id)
                  ? "validated"
                  : statuses.get(task.id) ||
                    (task.depends_on.every((d) => validated.has(d))
                      ? "ready"
                      : "blocked");
                return (
                  <g key={task.id} className={`dag-node ${status}`}>
                    <title>
                      {task.description} · depends on{" "}
                      {task.depends_on.join(", ") || "none"}
                    </title>
                    <rect x={p.x} y={p.y} width="190" height="60" rx="8" />
                    <text x={p.x + 12} y={p.y + 24}>
                      {task.id}
                    </text>
                    <text className="dag-status" x={p.x + 12} y={p.y + 44}>
                      {status}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
          <details>
            <summary>Specification, interfaces and acceptance criteria</summary>
            <div className="project-spec-grid">
              <div>
                <h3>Repository structure</h3>
                <pre>{spec.repository_structure.join("\n")}</pre>
                <h3>Technology stack</h3>
                <p>{spec.technology_stack.join(" · ")}</p>
                <h3>Components</h3>
                {spec.components.map((c) => (
                  <p key={c.id}>
                    <strong>{c.id}</strong>: {c.responsibility}
                    <br />
                    <code>{c.files.join(", ")}</code>
                  </p>
                ))}
              </div>
              <div>
                <h3>Interfaces</h3>
                {spec.interfaces.map((i, n) => (
                  <p key={n}>
                    <strong>
                      {i.source} → {i.target}
                    </strong>
                    <br />
                    {i.contract}
                  </p>
                ))}
                {[
                  ["Acceptance criteria", spec.acceptance_criteria],
                  ["Testing requirements", spec.testing_requirements],
                  ["Risks", spec.risks],
                  ["Assumptions", spec.assumptions],
                ].map(([label, items]) => (
                  <div key={label as string}>
                    <h3>{label}</h3>
                    <ul>
                      {(items as string[]).map((item) => (
                        <li key={item}>{item}</li>
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
            </div>
          </details>
          <h3>Checkpoint history</h3>
          <div className="checkpoint-history">
            {report.checkpoint_history?.map((entry) => (
              <div className="event" key={entry.number}>
                <time>{new Date(entry.at).toLocaleTimeString()}</time>
                <div>
                  <strong>
                    #{entry.number} {entry.label.replaceAll("_", " ")}
                  </strong>
                  <small>
                    <code>{entry.commit.slice(0, 12)}</code>
                  </small>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}
