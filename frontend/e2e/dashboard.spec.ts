import { expect, test } from "@playwright/test";

test("offline provider: browser task → real worktrees → integration → report and files", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/");
  await expect(page.locator(".topbar")).toContainText("Live updates");
  await expect(
    page.getByText("offline-example", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "New Task", exact: true }).click();
  await page
    .getByLabel("Task instructions")
    .fill("Build two independent Python modules with value constants");
  await page.getByRole("button", { name: /Start workflow/ }).click();
  await expect(page.locator(".run-actions .badge")).toHaveText("succeeded", {
    timeout: 30000,
  });
  await expect(page.getByText("2 / 2", { exact: true })).toBeVisible();
  await expect(
    page.locator(".agent").filter({ hasText: "module0.py" }),
  ).toContainText("completed");
  await expect(
    page.locator(".agent").filter({ hasText: "module1.py" }),
  ).toContainText("completed");
  await page.getByRole("button", { name: "module1.py ↗" }).click();
  await expect(page.locator(".file-preview pre")).toContainText("value = 1");
  const reportURL = await page
    .getByRole("link", { name: /JSON report/ })
    .getAttribute("href");
  const report = await (await page.request.get(reportURL!)).json();
  expect(report.succeeded).toBe(true);
  expect(report.tasks).toHaveLength(2);
  const [a, b] = report.tasks.map(
    (task: { attempts: { started_at: string; finished_at: string }[] }) =>
      task.attempts[0],
  );
  expect(
    Math.max(Date.parse(a.started_at), Date.parse(b.started_at)),
  ).toBeLessThan(
    Math.min(Date.parse(a.finished_at), Date.parse(b.finished_at)),
  );
  await page.getByRole("button", { name: /^Runs/ }).click();
  await expect(page.locator(".history .badge")).toHaveText("succeeded");
  await page.getByRole("button", { name: "Dashboard", exact: true }).click();
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(
    page.getByRole("button", { name: "New Task", exact: true }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
  expect(browserErrors).toEqual([]);
});
