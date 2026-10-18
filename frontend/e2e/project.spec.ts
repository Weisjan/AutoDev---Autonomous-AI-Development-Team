import { expect, test } from "@playwright/test";

test("project specification, real boundary pause and verified resume", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await page.getByRole("button", { name: "New Task", exact: true }).click();
  await page.getByLabel("Workflow type").selectOption("project");
  const option = page.getByRole("option", { name: /offline-project/ });
  await page
    .getByRole("combobox", { name: "Repository", exact: true })
    .selectOption((await option.getAttribute("value"))!);
  await page
    .getByLabel("Task instructions")
    .fill("Build a composed Python repository with incremental milestones");
  await page.getByRole("button", { name: /Start workflow/ }).click();
  await expect(
    page.getByRole("button", { name: "Pause at next checkpoint" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Pause at next checkpoint" }).click();
  await expect(page.locator(".run-actions .badge")).toHaveText("paused", {
    timeout: 30000,
  });
  await expect(
    page.getByRole("img", { name: "Task dependency graph" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Verify and resume project" }),
  ).toBeDisabled();
  await page.screenshot({
    path: "test-results/project-paused.png",
    fullPage: true,
  });
  await page.getByLabel(/I reviewed the checkpoint/).check();
  await page.getByRole("button", { name: "Verify and resume project" }).click();
  await expect(page.locator(".run-actions .badge")).toHaveText("succeeded", {
    timeout: 30000,
  });
  await expect(
    page.getByText("4 / 4 tasks validated · measured outcomes"),
  ).toBeVisible();
  await expect(page.locator(".milestone-card .badge")).toHaveText([
    "completed",
    "completed",
    "completed",
  ]);
  const url = await page
    .getByRole("link", { name: /JSON report/ })
    .getAttribute("href");
  const report = await (await page.request.get(url!)).json();
  expect(
    report.tasks.map((t: { attempts: unknown[] }) => t.attempts.length),
  ).toEqual([1, 1, 1, 1]);
  expect(report.model_calls_reserved).toBe(6);
  await page.getByRole("button", { name: "README.md ↗" }).click();
  await expect(page.locator(".file-preview pre")).toContainText(
    "documentation",
  );
  await page.screenshot({
    path: "test-results/project-complete.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/project-mobile.png",
    fullPage: true,
  });
  expect(errors).toEqual([]);
});
