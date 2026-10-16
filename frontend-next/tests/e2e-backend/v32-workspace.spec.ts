import { test, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { stubBackend } from "./backend-stub";
import {
  CASE_A,
  CASE_B,
  CASE_V3,
  SHIP_A,
  SHIP_V3,
  workerStatusDual,
  detailA,
  detailB,
  detailV3Route,
  queueRows,
} from "../fixtures/backend";
import { actionTraces } from "../fixtures/v32-actions";
import type { ApiCaseDetail, ApiPipelineEvent } from "../../src/api/contracts";

const captures = "../artifacts/v3.2-frontend-blockers/screenshots";
mkdirSync(captures, { recursive: true });

test("52 reported-resolved rows stay out of open and Waiting while slow or missing verification remains neutral", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const rows = Array.from({ length: 52 }, (_, index) => ({
    ...queueRows[1],
    case_id: index === 0 ? CASE_B : `SYN-RESOLVED-${index}`,
    shipment_id:
      index === 0 ? queueRows[1].shipment_id : `SYN-RESOLVED-SHIP-${index}`,
    workflow_state: "RESOLVED" as const,
  }));
  stub.state.queue = [queueRows[0], ...rows];
  let release!: () => void;
  const slow = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    (url) => url.pathname === `/cases/${CASE_B}`,
    async (route) => {
      await slow;
      await route.fulfill({ json: detailB() });
    },
  );
  await page.goto("/app/operations");
  await expect(page.locator("tbody tr")).toHaveCount(0);
  await expect(page.locator("tbody")).not.toContainText("SYN-RESOLVED");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  const panel = page.getByRole("complementary", {
    name: "Waiting and closed cases",
  });
  await expect(panel.getByRole("tabpanel")).not.toContainText(
    rows[0].shipment_id,
  );
  await panel.getByRole("tab", { name: /Closed/ }).click();
  await expect(panel.getByTestId("resolution-pending-count")).toContainText(
    "52 unconfirmed",
  );
  await expect(panel.locator(".resolved-entry")).toHaveCount(52);
  await expect(panel.locator(".verified-check")).toHaveCount(0);
  const queueViewport = panel
    .getByRole("tabpanel")
    .locator('[data-slot="scroll-area-viewport"]');
  expect((await queueViewport.boundingBox())!.height).toBeLessThanOrEqual(400);
  await queueViewport.evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect(
    panel.getByRole("link", { name: new RegExp(rows[51].shipment_id) }),
  ).toBeInViewport();
  await queueViewport.evaluate((element) => {
    element.scrollTop = 0;
  });
  await page.screenshot({
    path: `${captures}/resolved-verification-pending.png`,
    fullPage: true,
  });
  await expect(panel.locator(".resolved-entry").first()).toContainText(
    /checking verification|verification unavailable/,
  );
  release();
  await expect(panel.locator(".verified-check")).toHaveCount(1);
  await expect(panel.getByTestId("resolution-pending-count")).toContainText(
    "51 unconfirmed",
  );
  await panel.getByRole("tab", { name: /Waiting/ }).click();
  await expect(panel.getByRole("tabpanel")).not.toContainText("SYN-RESOLVED");
  await expect(page.locator("tbody tr")).toHaveCount(0);
  expect(stub.posts).toEqual([]);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`desktop workspace preserves density and visualization focus at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const stub = await stubBackend(page);
    stub.state.dualWorker = true;
    await page.goto(`/app/cases/${CASE_A}`);
    await expect(page.getByTestId("synthetic-data-label")).toBeVisible();
    const workers = page.getByTestId("working-agents");
    await expect(workers.getByRole("link")).toHaveCount(2);
    await expect(
      page.getByTestId("knowledge-graph").locator(".entity-node").first(),
    ).toBeVisible();
    const map = page.getByTestId("route-map");
    const graph = page.getByTestId("knowledge-graph");
    const balancedMap = (await map.boundingBox())!;
    const balancedGraph = (await graph.boundingBox())!;
    expect(Math.abs(balancedMap.y - balancedGraph.y)).toBeLessThan(2);
    expect(balancedMap.width).toBeGreaterThan(400);
    expect(balancedGraph.width).toBeGreaterThan(400);
    // Measure the evidence canvases, not the surrounding cards. Scrolling is
    // preferable to shrinking map tiles and graph labels below a usable size.
    expect(balancedMap.height).toBeGreaterThanOrEqual(400);
    expect(balancedGraph.height).toBeGreaterThanOrEqual(400);
    writeFileSync(
      `${captures}/desktop-${viewport.width}x${viewport.height}.json`,
      JSON.stringify(
        { viewport, map: balancedMap, graph: balancedGraph },
        null,
        2,
      ),
    );
    expect(balancedMap.y + balancedMap.height).toBeLessThanOrEqual(
      viewport.height + 130,
    );
    // Assignments now live in the collapsed left nav, outside the case canvas.
    expect(
      (await workers.getByRole("link").first().boundingBox())!.height,
    ).toBeLessThan(40);
    expect((await workers.boundingBox())!.x).toBeLessThan(balancedMap.x);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(viewport.width);
    await expect(
      page.getByRole("separator", { name: "Resize map and graph" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Map focus", exact: true }).click();
    await expect
      .poll(async () => (await map.boundingBox())!.width)
      .toBeGreaterThan(balancedMap.width * 1.2);
    await page
      .getByRole("button", { name: "Graph focus", exact: true })
      .click();
    await expect
      .poll(async () => (await graph.boundingBox())!.width)
      .toBeGreaterThan(balancedGraph.width * 1.2);
    await page
      .getByRole("button", { name: "Balanced view", exact: true })
      .click();
    await expect
      .poll(async () =>
        Math.abs((await map.boundingBox())!.width - balancedMap.width),
      )
      .toBeLessThan(2);
    await page.screenshot({
      path: `${captures}/desktop-${viewport.width}x${viewport.height}.png`,
      fullPage: true,
    });
    expect(stub.posts).toEqual([]);
  });
}

test("one workspace switches between two real worker claims without mixing evidence or starting work", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const dual = structuredClone(workerStatusDual);
  dual.worker.active_cases![1] = {
    ...dual.worker.active_cases![1],
    case_id: CASE_V3,
    shipment_id: SHIP_V3,
    run_id: "SYN-RUN-V3",
  };
  const a = detailA({ workflow_state: "INVESTIGATING" });
  const b = detailV3Route({
    workflow_state: "INVESTIGATING",
    last_run_id: "SYN-RUN-V3",
    run: { entity_id: "SYN-RUN-V3", status: "RUNNING" },
  });
  stub.state.detailA = a;
  stub.state.detailV3 = b;
  const call: ApiPipelineEvent = {
    sequence: 100,
    stage: "classify",
    status: "RUNNING",
    recorded_at: "2026-09-03T14:00:30+00:00",
    output: {
      kind: "tool_call",
      tool: "custody_chain",
      purpose: "Trace the recorded custody source",
      evidence_ids: [`${SHIP_A}-CUST-02-01`],
    },
  };
  await page.route("**/worker/status", (route) =>
    route.fulfill({ json: dual }),
  );
  await page.route("**/events", (route) => {
    const id = new URL(route.request().url()).pathname.split("/")[2];
    const detail = id === CASE_A ? a : b;
    return route.fulfill({
      contentType: "text/event-stream",
      body: `event: pipeline\ndata: ${JSON.stringify({
        workflow_state: detail.workflow_state,
        state_version: detail.state_version,
        run_id: id === CASE_A ? "SYN-RUN-1" : "SYN-RUN-V3",
        status: "RUNNING",
        events: id === CASE_A ? [call] : [],
      })}\n\n`,
    });
  });
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(
    page.getByTestId("working-agents").getByRole("link"),
  ).toHaveCount(2);
  await expect(page.getByTestId("retrieval-100")).toBeVisible();
  await page.getByTestId("retrieval-100").click();
  await expect(
    page
      .getByTestId("knowledge-graph")
      .locator(`[data-id="${SHIP_A}-CUST-02-01"] .entity-node`),
  ).toHaveClass(/evidence-selected/);
  await expect(
    page.getByTestId("route-map").locator(".evidence-marker.selected"),
  ).toHaveCount(1);
  await expect(page.getByTestId("evidence-inspector")).toContainText("LOADED");
  mkdirSync(captures, { recursive: true });
  await page.screenshot({
    path: `${captures}/selected-retrieval.png`,
    fullPage: true,
  });
  await page.getByTestId(`worker-case-${CASE_V3}`).click();
  await expect(page).toHaveURL(new RegExp(CASE_V3));
  await expect(
    page
      .getByTestId("knowledge-graph")
      .locator(`[data-id="${b.route_evidence!.source_nodes[0].id}"]`),
  ).toBeVisible();
  await expect(
    page.getByTestId("knowledge-graph").locator(`[data-id^="${SHIP_A}"]`),
  ).toHaveCount(0);
  await expect(page.getByTestId("retrieval-100")).toHaveCount(0);
  await expect(
    page.getByTestId("route-map").locator(".evidence-marker.confirmed"),
  ).toHaveCount(0);
  await expect(
    page.getByTestId("route-map").locator(".evidence-marker.selected"),
  ).toHaveCount(0);
  await expect(page.getByTestId("evidence-inspector")).toHaveClass(/idle/);
  await page.screenshot({
    path: `${captures}/second-worker-case.png`,
    fullPage: true,
  });
  expect(stub.posts).toEqual([]);
  a.workflow_state = "AWAITING_OUTCOME";
  a.state_version += 1;
  stub.state.queue = stub.state.queue.map((row) =>
    row.case_id === CASE_A
      ? {
          ...row,
          workflow_state: "AWAITING_OUTCOME",
          state_version: a.state_version,
        }
      : row,
  );
  dual.worker.active_cases = [dual.worker.active_cases![1]];
  dual.worker.active_count = 1;
  await expect(page.getByTestId("worker-capacity")).toContainText(
    "1 available",
    { timeout: 10000 },
  );
  expect(stub.posts).toEqual([]);
});

test("actual route observation selection focuses its segmented vehicle path", async ({
  page,
}) => {
  await stubBackend(page);
  await page.route("**/events", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": no new frames\n\n",
    }),
  );
  const detail = detailV3Route();
  const id = detail.route_evidence!.observations[0].evidence_id;
  await page.goto(`/app/cases/${CASE_V3}`);
  await page.getByTestId(`chronology-${id}`).click();
  await expect(
    page.getByTestId("route-map").locator('.vehicle-route[stroke-width="4"]'),
  ).toHaveCount(1);
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "Vehicle telemetry",
  );
  await expect(
    page
      .getByTestId("knowledge-graph")
      .locator(`[data-id="${id}"] .entity-node`),
  ).toHaveClass(/evidence-selected/);
});

test("unlocated retrieval remains graph-only and never fabricates a map focus", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const id = `${SHIP_A}-SCAN-0`;
  stub.state.detailA = detailA({
    pipeline: {
      status: "REVIEWED",
      events: [
        {
          sequence: 99,
          stage: "classify",
          status: "COMPLETED",
          output: {
            kind: "tool_call",
            tool: "scans",
            evidence_ids: [id, "SYN-COMPUTED-NOT-A-NODE"],
            computed_ids: ["SYN-COMPUTED-NOT-A-NODE"],
          },
        },
      ],
    },
  });
  await page.route("**/events", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": no new frames\n\n",
    }),
  );
  await page.goto(`/app/cases/${CASE_A}`);
  await page.getByTestId("retrieval-99").click();
  await expect(page.getByTestId("retrieval-activity")).toContainText(
    "No grounded geographic link",
  );
  await expect(page.getByTestId("retrieval-activity")).toContainText(
    "unavailable in this bounded graph",
  );
  await expect(
    page.getByTestId("route-map").locator(".evidence-marker.selected"),
  ).toHaveCount(0);
  await expect(
    page.getByTestId("knowledge-graph").locator(`[data-id="${id}"]`),
  ).toBeVisible();
  expect(stub.posts).toEqual([]);
});

test("Waiting/Resolved follows a saved verifier result; accepting a task never resolves it", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const trace = actionTraces.find(
    (item) => item.workflow === "barcode-independent-rescan",
  )!;
  const accepted = structuredClone(trace.action_status);
  accepted.resolution = "OPERATIONAL_WORK_PENDING";
  accepted.actions = accepted.actions.map((action) => ({
    ...action,
    state: "ACCEPTED",
    operational_label: "AWAITING_RESCAN",
    resolved: false,
    verification: "NOT_REQUESTED",
    events: action.events.slice(
      0,
      action.events.findIndex((event) => event.kind === "ACCEPTED") + 1,
    ),
  }));
  let current: ApiCaseDetail = {
    case_id: trace.case_id,
    shipment_id: trace.shipment_id,
    workflow_state: "AWAITING_OUTCOME",
    state_version: 20,
    evidence: { nodes: [], edges: [] },
    action_status: accepted,
    outcome: null,
  };
  stub.state.queue = [
    {
      ...queueRows[0],
      case_id: trace.case_id,
      shipment_id: trace.shipment_id,
      workflow_state: "AWAITING_OUTCOME",
      state_version: 20,
    },
  ];
  await page.route(
    (url) => url.pathname === `/cases/${trace.case_id}`,
    (route) => route.fulfill({ json: current }),
  );
  await page.route("**/events", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": no new frames\n\n",
    }),
  );
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(page.getByRole("tabpanel")).toContainText(
    "Awaiting independent rescan",
  );
  await page.getByRole("tab", { name: /^Closed/ }).click();
  await expect(page.getByRole("tabpanel")).toContainText("No closed cases");
  current = {
    ...current,
    workflow_state: trace.workflow_state,
    state_version: 21,
    action_status: trace.action_status,
    outcome: trace.outcome,
  };
  stub.state.queue[0] = {
    ...stub.state.queue[0],
    workflow_state: trace.workflow_state,
    state_version: 21,
  };
  await expect(page.getByRole("tabpanel").getByRole("link")).toHaveCount(1, {
    timeout: 10000,
  });
  await page.getByRole("tabpanel").getByRole("link").click();
  await expect(page.getByTestId("action-resolution")).toContainText(
    "Shipment exception verified resolved",
  );
  await page.getByTestId("action-lifecycle").locator("summary").click();
  await expect(page.getByTestId("action-lifecycle")).toContainText(
    trace.outcome!.rule_id!,
  );
  await page.screenshot({
    path: `${captures}/verified-resolution.png`,
    fullPage: true,
  });
  expect(stub.posts).toEqual([]);
});

test("V3.2 rejection overrides an inconsistent legacy brief without green resolution", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const trace = actionTraces.find(
    (item) => item.workflow === "rejected-duplicate-late-response",
  )!;
  const current: ApiCaseDetail = {
    case_id: trace.case_id,
    shipment_id: trace.shipment_id,
    workflow_state: trace.workflow_state,
    state_version: 30,
    evidence: { nodes: [], edges: [] },
    action_status: trace.action_status,
    outcome: trace.outcome,
    brief: {
      resolved: true,
      waiting_label_en: "Resolved",
      lines: [
        { key: "action", label_en: "Action", text_en: "request not delivered" },
        { key: "status", label_en: "Status", text_en: "Resolved" },
      ],
    },
  };
  stub.state.queue = [
    {
      ...queueRows[0],
      case_id: trace.case_id,
      shipment_id: trace.shipment_id,
      workflow_state: trace.workflow_state,
      state_version: 30,
    },
  ];
  await page.route(
    (url) => url.pathname === `/cases/${trace.case_id}`,
    (route) => route.fulfill({ json: current }),
  );
  await page.route("**/events", (route) =>
    route.fulfill({
      contentType: "text/event-stream",
      body: ": no new frames\n\n",
    }),
  );
  await page.goto(`/app/cases/${trace.case_id}`);
  await expect(page.getByTestId("case-assessment")).toContainText(
    "Task rejected",
  );
  await expect(page.getByTestId("case-assessment")).not.toContainText(
    "request not delivered",
  );
  await expect(
    page.getByTestId("case-assessment").locator(".assessment-state.resolved"),
  ).toHaveCount(0);
  await expect(page.getByTestId("action-resolution")).toContainText(
    "Task rejected",
  );
  await expect(page.getByTestId("graph-empty-state")).toContainText(
    "No source graph records",
  );
  await expect(page.getByTestId("map-empty-state")).toContainText(
    "No located source observations",
  );
  await page.getByTestId("action-lifecycle").locator("summary").click();
  await expect(page.getByTestId("action-lifecycle")).toContainText(
    "audit history only",
  );
  expect(stub.posts).toEqual([]);
});
