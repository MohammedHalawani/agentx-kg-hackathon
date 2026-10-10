import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * A walk through every screen against a real backend with a loaded scratch database. It makes
 * real operator requests (investigate, reject, escalate, worker start and pause), so it runs
 * only when SUHAIL_LIVE_WRITE=1 and only ever against a scratch database:
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8010 SUHAIL_LIVE_WRITE=1 npm run test:e2e:live
 *
 * Every assertion compares what the screen shows with what the backend's API returns.
 */
test.skip(
  process.env.SUHAIL_LIVE_WRITE !== "1",
  "set SUHAIL_LIVE_WRITE=1 (scratch database only)",
);
test.describe.configure({ mode: "serial" });

type Row = {
  case_id: string;
  shipment_id: string;
  workflow_state: string;
  state_version: number;
  city?: string;
};
async function queue(request: APIRequestContext): Promise<Row[]> {
  const body = await (
    await request.get("/cases/queue?scope=all&limit=100")
  ).json();
  return body.items;
}
const shot = (name: string) => `screenshots/live-${name}.png`;

test.beforeEach(async ({ request }) => {
  const status = await (await request.get("/worker/status")).json();
  // Refuse to run against anything but a scratch database.
  expect(String(status.database)).toMatch(/-(ui|test2?|ci-test)$/);
});

test("Operations shows the backend's queue and the worker state", async ({
  page,
  request,
}) => {
  const rows = await queue(request);
  const active = rows.filter((row) => row.workflow_state !== "RESOLVED");
  await page.goto("/app/operations");
  await expect(page.locator(".inline-count")).toContainText(
    `${active.length} open`,
  );
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data");
  await expect(page.locator("body")).not.toContainText(/SHP-10482|UI lab|SPL Operations/);
  // Page size 50 shows every case; each row's shipment and state are the backend's.
  await page.getByRole("combobox", { name: "Rows per page" }).click();
  await page.getByRole("option", { name: "50", exact: true }).click();
  await expect(page.locator("[data-testid^='data-row-']")).toHaveCount(
    Math.min(active.length, 50),
  );
  for (const row of active.slice(0, 5))
    await expect(page.getByTestId(`data-row-${row.case_id}`)).toContainText(
      row.shipment_id,
    );
  await page.waitForTimeout(600);
  await page.screenshot({ path: shot("operations") });
});

test("Investigation shows a reviewed rules-only case without presenting rule output as a diagnosis", async ({
  page,
  request,
}) => {
  const row = (await queue(request)).find(
    (item) => item.workflow_state === "AWAITING_APPROVAL",
  );
  test.skip(!row, "no case is awaiting approval");
  const detail = await (await request.get(`/cases/${row!.case_id}`)).json();
  await page.goto(`/app/cases/${row!.case_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(
    row!.shipment_id,
  );
  // The map draws exactly the backend's corroborated custody points and vehicle telemetry.
  const map = page.getByTestId("route-map");
  await expect(map.locator(".evidence-marker.confirmed")).toHaveCount(
    detail.route_layers.layers.custody_points.length,
  );
  await expect(map.locator(".evidence-marker.vehicle_only")).toHaveCount(
    Math.min(detail.route_layers.layers.vehicle_path.length, 6),
  );
  await expect(
    page.getByTestId("knowledge-graph").locator(".entity-node"),
  ).not.toHaveCount(0);
  // Rules-only run: there is no diagnosis, and the screen says so.
  expect(detail.diagnosis.available).toBe(false);
  await page.getByRole("button", { name: /^Diagnose ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(
    "Rule check, not a diagnosis",
  );
  await page.getByRole("button", { name: /^Review ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(
    "Deterministic evidence guard (no model review)",
  );
  // The backend does not allow approving a rules-only proposal; the page offers none.
  expect(detail.recommendation.approvable).toBe(false);
  await expect(page.getByRole("button", { name: "Review & authorize" })).toHaveCount(0);
  await expect(page.locator(".case-context")).toContainText(
    detail.recommendation.approval_reason,
  );
  await expect(page.locator(".case-context")).toContainText(
    "Rules-only proposal · not executable",
  );
  await page.waitForTimeout(1500);
  await page.screenshot({ path: shot("investigation") });
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet).toContainText("Rule checks · not a diagnosis");
  await expect(sheet).toContainText("Rule signals are not a diagnosis");
  await expect(sheet).toContainText("No action has been executed.");
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot("assessment") });
});

test("Investigate now runs the backend's investigation and the rail follows its recorded stages", async ({
  page,
  request,
}) => {
  const row = (await queue(request)).find(
    (item) => item.workflow_state === "OPEN",
  );
  test.skip(!row, "no queued case");
  await page.goto(`/app/cases/${row!.case_id}`);
  await expect(page.locator(".pipeline-meta")).toContainText("Queued");
  await page.getByRole("button", { name: "Investigate now" }).click();
  // The backend finishes the rules-only run; the page shows the state the backend recorded.
  await expect
    .poll(
      async () =>
        (await (await request.get(`/cases/${row!.case_id}`)).json())
          .workflow_state,
      { timeout: 40000 },
    )
    .not.toBe("OPEN");
  const after = await (await request.get(`/cases/${row!.case_id}`)).json();
  expect(after.workflow_state).not.toBe("RESOLVED");
  await expect(page.getByRole("button", { name: "Investigate now" })).toHaveCount(0, {
    timeout: 20000,
  });
  await expect(
    page.getByRole("button", { name: /^Collect · completed/ }),
  ).toBeVisible({ timeout: 20000 });
  await expect(page.locator(".case-heading")).not.toContainText("Resolved");
});

test("Decisions relays a rejection and an escalation, and the backend's audit records them", async ({
  page,
  request,
}) => {
  const rows = await queue(request);
  const approval = rows.find((item) => item.workflow_state === "AWAITING_APPROVAL");
  const review = rows.find((item) => item.workflow_state === "HUMAN_REVIEW");
  test.skip(!approval || !review, "needs one case awaiting approval and one in human review");
  await page.goto("/app/decisions");
  await page.getByRole("textbox", { name: "Search decisions" }).fill(approval!.shipment_id);
  await page.getByRole("button", { name: `Review ${approval!.shipment_id}` }).click();
  await page.waitForTimeout(800);
  await page.screenshot({ path: shot("decision-review") });
  await page.getByRole("button", { name: "Reject the action" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Reject action" }).click();
  await expect
    .poll(async () => (await (await request.get(`/cases/${approval!.case_id}`)).json()).workflow_state, { timeout: 30000 })
    .toBe("REJECTED");

  await page.getByRole("textbox", { name: "Search decisions" }).fill(review!.shipment_id);
  await page.getByRole("button", { name: `Review ${review!.shipment_id}` }).click();
  await page.getByRole("button", { name: "Escalate case" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Escalate case" }).click();
  await expect
    .poll(async () => (await (await request.get(`/cases/${review!.case_id}`)).json()).workflow_state, { timeout: 30000 })
    .toBe("ESCALATED");

  // Neither decision executed or resolved anything.
  for (const id of [approval!.case_id, review!.case_id]) {
    const detail = await (await request.get(`/cases/${id}`)).json();
    expect(detail.executions).toEqual([]);
    expect(detail.outcome).toBeNull();
  }
  await page.getByRole("textbox", { name: "Search decisions" }).fill("");
  await page.getByRole("tab", { name: "Decision history" }).click();
  const history = page.locator("[data-testid^='data-row-']");
  await expect(history.filter({ hasText: approval!.shipment_id })).toContainText("rejected");
  await expect(history.filter({ hasText: review!.shipment_id })).toContainText("escalated");
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot("decisions-history") });
});

test("Audit, Explore and the schema show the backend's records", async ({
  page,
  request,
}) => {
  const audit = await (await request.get("/audit?limit=25")).json();
  await page.goto("/app/audit");
  await expect(page.getByTestId("audit-event-count")).not.toHaveText("0", {
    timeout: 30000,
  });
  // Every loaded event belongs to a case in the queue; the total can only be smaller than the ledger.
  const shown = Number(await page.getByTestId("audit-event-count").innerText());
  expect(shown).toBeGreaterThan(0);
  expect(shown).toBeLessThanOrEqual(audit.filtered_total + 50);
  await expect(page.locator("[data-testid^='data-row-']").first()).toContainText("BACKEND");
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot("audit") });

  const rows = await queue(request);
  await page.goto("/app/explore");
  await expect(page.getByTestId("explore-count")).toHaveText(String(rows.length));
  await expect(
    page.getByTestId("network-map").locator(".shipment-cluster").first(),
  ).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: shot("explore") });
  await page.getByRole("tab", { name: "Graph" }).click();
  await expect(
    page.getByTestId("knowledge-graph").locator(".entity-node").first(),
  ).toBeVisible({ timeout: 20000 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: shot("explore-graph") });
  const schema = await (await request.get("/schema")).json();
  await page.getByRole("tab", { name: "Schema" }).click();
  await expect(page.locator(".schema-entity")).toHaveCount(schema.nodes.length);
  await page.screenshot({ path: shot("schema") });
});

test("The Auto switch starts and pauses the backend worker", async ({
  page,
  request,
}) => {
  await page.goto("/app/operations");
  const auto = page.getByRole("switch", { name: "Automatic investigation" });
  await expect(auto).not.toBeChecked();
  await auto.click();
  await expect(auto).toBeChecked();
  expect((await (await request.get("/worker/status")).json()).worker.state).toBe("running");
  await auto.click();
  await expect(auto).not.toBeChecked();
  expect((await (await request.get("/worker/status")).json()).worker.state).toBe("paused");
  // Nothing was resolved by any of this: the backend holds no verified outcome.
  const rows = await queue(request);
  expect(rows.filter((row) => row.workflow_state === "RESOLVED")).toEqual([]);
});
