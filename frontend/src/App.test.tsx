import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const fetchMock = vi.fn();
const project = {
  id: "0123456789ab",
  name: "Example project",
  path: "D:/Example",
  branch: "feature/demo",
  dirty: false,
};
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockImplementation(async (path: string, options?: RequestInit) => {
    let data: unknown = {};
    if (path === "/api/session") data = { csrf: "test-csrf" };
    if (path === "/api/projects") data = [project];
    if (path === "/api/runs") data = [];
    if (path === "/api/settings")
      data = {
        provider: "codex_cli",
        authentication: "Existing ChatGPT login",
      };
    if (path.startsWith("/api/runs/") && path.endsWith("/files")) data = [];
    if (options?.method === "POST")
      return {
        ok: false,
        json: async () => ({ detail: "A workflow is already active" }),
      };
    return { ok: true, json: async () => data };
  });
});

describe("dashboard interactions", () => {
  it("loads repositories and shows an honest empty state", async () => {
    render(<App />);
    expect(await screen.findByText("Example project")).toBeVisible();
    expect(screen.getByText("Your next build starts here")).toBeVisible();
    expect(screen.queryByText("succeeded")).not.toBeInTheDocument();
  });
  it("submits bounded form inputs with the session CSRF token and shows API errors", async () => {
    render(<App />);
    await screen.findByText("Example project");
    fireEvent.click(screen.getByRole("button", { name: "New Task" }));
    expect(screen.getByLabelText("Parallel developers")).toHaveValue(2);
    expect(screen.getByLabelText("Parallel developers")).toHaveAttribute(
      "max",
      "2",
    );
    fireEvent.change(screen.getByLabelText("Task instructions"), {
      target: { value: "Implement two useful Python modules" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Start workflow/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A workflow is already active",
    );
    const call = fetchMock.mock.calls.find(
      ([, options]) => options?.method === "POST",
    );
    expect(call?.[1].headers["X-AutoDev-CSRF"]).toBe("test-csrf");
    expect(JSON.parse(call?.[1].body)).toMatchObject({
      repository_id: project.id,
      concurrency: 2,
      max_corrections: 3,
    });
  });
  it("shows persisted interrupted runs without an active cancellation button", async () => {
    const run = {
      id: "0123456789ab:aaaaaaaaaaaa",
      run_id: "aaaaaaaaaaaa",
      repository_id: project.id,
      instructions: "Previous workflow",
      status: "interrupted",
      stage: "interrupted",
      started_at: "2026-01-01",
      finished_at: "",
      report: null,
      events: [],
    };
    const defaultImplementation = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path, options) =>
      path === "/api/runs"
        ? Promise.resolve({ ok: true, json: async () => [run] })
        : path === `/api/runs/${run.id}`
          ? Promise.resolve({ ok: true, json: async () => run })
          : defaultImplementation(path, options),
    );
    render(<App />);
    await waitFor(() =>
      expect(screen.getAllByText("interrupted").length).toBeGreaterThan(0),
    );
    expect(
      screen.queryByRole("button", { name: "Cancel workflow" }),
    ).not.toBeInTheDocument();
  });
  it("requests cancellation and disables repeated cancellation while cleanup is pending", async () => {
    let run = {
      id: "0123456789ab:bbbbbbbbbbbb",
      run_id: "bbbbbbbbbbbb",
      repository_id: project.id,
      instructions: "Running workflow",
      status: "running",
      stage: "planning",
      started_at: "2026-01-01",
      finished_at: "",
      report: null,
      events: [],
    };
    const fallback = fetchMock.getMockImplementation()!;
    fetchMock.mockImplementation((path, options) => {
      if (path === `/api/runs/${run.id}/cancel` && options?.method === "POST") {
        run = { ...run, status: "cancelling" };
        return Promise.resolve({ ok: true, json: async () => run });
      }
      if (path === "/api/runs")
        return Promise.resolve({ ok: true, json: async () => [run] });
      if (path === `/api/runs/${run.id}`)
        return Promise.resolve({ ok: true, json: async () => run });
      return fallback(path, options);
    });
    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Cancel workflow" }),
    );
    expect(
      await screen.findByRole("button", { name: "Waiting for cleanup…" }),
    ).toBeDisabled();
    expect(
      fetchMock.mock.calls.filter(([path]) => path.endsWith("/cancel")),
    ).toHaveLength(1);
  });
  it("loads safe configuration on the Settings page", async () => {
    render(<App />);
    await screen.findByText("Example project");
    fireEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(await screen.findByText("codex_cli")).toBeVisible();
    expect(screen.getByText(/Browser inputs cannot expand/)).toBeVisible();
  });
});
