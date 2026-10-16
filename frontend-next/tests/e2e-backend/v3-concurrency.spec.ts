import { test, expect } from "@playwright/test";
import { stubBackend } from "./backend-stub";

test("Operations shows two active investigations from worker.active_cases", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.dualWorker = true;
  stub.state.worker = "running";
  await page.goto("/app/operations");
  await expect(page.getByTestId("working-agents")).toBeVisible();
  await expect(page.getByTestId("working-agents")).toContainText("2 / 2");
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await expect(
    page.getByTestId("working-agents").getByRole("link"),
  ).toHaveCount(2);
});
