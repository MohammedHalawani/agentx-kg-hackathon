import { test, expect } from "@playwright/test";
import { stubBackend } from "./backend-stub";

test("Operations shows two active investigations from worker.active_cases", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.dualWorker = true;
  stub.state.worker = "running";
  await page.goto("/app/operations");
  await expect(page.getByTestId("active-investigations")).toBeVisible();
  await expect(page.getByText("2 active investigations")).toBeVisible();
  await expect(
    page.getByTestId("active-investigations").getByRole("link"),
  ).toHaveCount(2);
});
