import { expect, test } from "@playwright/test";

/**
 * What the screens show must be what the backend serves at that moment: the queue the API
 * returns, or a plain statement that the backend is unavailable. Read-only.
 */
test("The app served under /app/ shows exactly what the backend's API returns", async ({
  page,
  request,
}) => {
  const shell = await request.get("/app/");
  expect(shell.status()).toBe(200);
  expect(await shell.text()).toContain("/app/assets/");
  // A page route reloads into the app shell; the API route of the same name stays an API.
  expect((await request.get("/app/audit")).headers()["content-type"]).toContain("text/html");
  const audit = await request.get("/audit?limit=25");
  expect(audit.headers()["content-type"]).toContain("application/json");

  const status = await request.get("/worker/status");
  const queue = await request.get("/cases/queue?scope=all&limit=100");
  await page.goto("/app/operations");
  const rows = page.locator("[data-testid^='data-row-']");
  await expect(page.locator("body")).not.toContainText(/SHP-10482|UI lab|Noura Al-Salem/);

  if (!status.ok() || !queue.ok()) {
    // The backend cannot serve operations (for example its graph database is down).
    await expect(page.locator(".backend-notice")).toContainText(
      "The Suhail backend is not reachable",
    );
    await expect(page.locator(".environment-badge")).toHaveText("Backend offline");
    await expect(rows).toHaveCount(0);
    await expect(page.locator(".backend-notice")).toContainText(
      (await status.json()).detail,
    );
    test.info().annotations.push({
      type: "backend",
      description: `operations unavailable (${status.status()}): offline state verified`,
    });
    return;
  }

  const body = await queue.json();
  const active = body.items.filter(
    (row: { workflow_state: string }) => row.workflow_state !== "RESOLVED",
  );
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data");
  await expect(page.locator(".inline-count")).toContainText(`${active.length} open`);
  if (active.length) {
    const first = active[0] as { case_id: string; shipment_id: string };
    await page.goto(`/app/cases/${first.case_id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(first.shipment_id);
    const detail = await (await request.get(`/cases/${first.case_id}`)).json();
    // The page never shows a case as resolved unless the backend says so.
    if (detail.workflow_state !== "RESOLVED")
      await expect(page.locator(".case-heading")).not.toContainText("Resolved");
    if (!detail.diagnosis?.available)
      await expect(page.locator(".case-context")).not.toContainText(
        String(detail.diagnosis?.unaccepted_investigation?.summary ?? "\u0000"),
      );
  }
  test.info().annotations.push({
    type: "backend",
    description: `online: ${body.items.length} cases in ${(await status.json()).database}`,
  });
});
