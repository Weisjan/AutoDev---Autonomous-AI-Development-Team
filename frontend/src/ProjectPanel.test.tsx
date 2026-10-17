import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ProjectPanel from "./ProjectPanel";
import type { Run } from "./types";

const run = {
  id: "abcdef012345:012345abcdef",
  status: "paused",
  report: {
    mode: "project",
    tasks: [],
    checkpoint_safe: true,
    validated_tasks: ["base"],
    milestones: [{ id: "first", status: "completed" }],
    checkpoint_history: [
      {
        number: 1,
        at: "2026-01-01",
        label: "architecture_validated",
        commit: "abc123",
      },
    ],
    specification: {
      title: "Project specification",
      summary: "Real measured state",
      technology_stack: ["Python"],
      repository_structure: ["base.py", "app.py"],
      components: [],
      interfaces: [],
      acceptance_criteria: [],
      testing_requirements: [],
      risks: [],
      assumptions: [],
      tasks: [
        {
          id: "base",
          description: "Base",
          owned_files: ["base.py"],
          depends_on: [],
        },
        {
          id: "app",
          description: "App",
          owned_files: ["app.py"],
          depends_on: ["base"],
        },
      ],
      milestones: [
        {
          id: "first",
          description: "First milestone",
          task_ids: ["base"],
          acceptance_criteria: ["passes"],
        },
      ],
    },
  },
} as unknown as Run;

beforeEach(() =>
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...run, status: "running" }),
    }),
  ),
);

it("renders the specification, measured dependency state and checkpoint history", () => {
  render(<ProjectPanel run={run} changed={vi.fn()} />);
  expect(screen.getByText("Project specification")).toBeVisible();
  expect(
    screen.getByRole("img", { name: "Task dependency graph" }),
  ).toBeVisible();
  expect(
    screen.getByText("validated", { selector: "text" }),
  ).toBeInTheDocument();
  expect(screen.getByText("ready", { selector: "text" })).toBeInTheDocument();
  expect(screen.getByText(/architecture validated/)).toBeVisible();
});

it("requires explicit confirmation and sends the supported resume request", async () => {
  const changed = vi.fn();
  render(<ProjectPanel run={run} changed={changed} />);
  const button = screen.getByRole("button", {
    name: "Verify and resume project",
  });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(button);
  expect(
    await screen.findByRole("button", { name: "Verify and resume project" }),
  ).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledWith(
    `/api/runs/${run.id}/resume`,
    expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    }),
  );
});

it("does not offer force-resume when the boundary is unsafe", () => {
  render(
    <ProjectPanel
      run={{
        ...run,
        status: "interrupted",
        report: { ...run.report!, checkpoint_safe: false },
      }}
      changed={vi.fn()}
    />,
  );
  expect(
    screen.queryByRole("button", { name: /resume project/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByText(/Force-resume is disabled/)).toBeVisible();
});
