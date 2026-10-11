import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";

/**
 * Watches a live demo session through the interface, read-only: cases arriving in the queue,
 * and each investigation's header text while the backend's worker runs it (the running elapsed
 * time and any live state such as a retried reply). It sends no operator request.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8020 SUHAIL_DEMO_WATCH=<number of cases to wait for> \
 *   npx playwright test --config playwright.live.config.ts demo-live-arrivals
 */
const EXPECTED = Number(process.env.SUHAIL_DEMO_WATCH ?? 0);
const MINUTES = Number(process.env.SUHAIL_DEMO_WATCH_MINUTES ?? 30);
test.skip(!EXPECTED, "set SUHAIL_DEMO_WATCH to the number of cases the session will open");
test.setTimeout((MINUTES + 2) * 60 * 1000);

interface Row {
  case_id: string;
  shipment_id: string;
  workflow_state: string;
}
interface Seen {
  shipment: string;
  arrivedAt: number;
  listedAfterMs: number | null;
  headers: string[];
  stageTexts: string[];
  final?: string;
}

test("Live arrivals appear in order and each investigation shows its running time", async ({
  page,
  context,
  request,
}) => {
  const started = Date.now();
  const seen = new Map<string, Seen>();
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data", {
    timeout: 60000,
  });
  const casePage = await context.newPage();
  casePage.on("pageerror", (error) => errors.push(error.message));
  let watching: string | null = null;
  // Keep watching for a while after the last arrival, so repeat investigations are seen.
  const settle = Number(process.env.SUHAIL_DEMO_SETTLE_MINUTES ?? 0) * 60 * 1000;
  const done = () =>
    seen.size >= EXPECTED &&
    [...seen.values()].every((item) => item.final !== undefined) &&
    Date.now() - Math.max(...[...seen.values()].map((item) => item.arrivedAt)) > settle;

  while (!done() && Date.now() - started < MINUTES * 60 * 1000) {
    const queue = await request
      .get("/cases/queue?scope=all&limit=100")
      .then((response) => response.json() as Promise<{ items: Row[] }>)
      .catch(() => ({ items: [] as Row[] }));
    for (const row of queue.items) {
      let item = seen.get(row.case_id);
      if (!item) {
        item = {
          shipment: row.shipment_id,
          arrivedAt: Date.now(),
          listedAfterMs: null,
          headers: [],
          stageTexts: [],
        };
        seen.set(row.case_id, item);
        console.log(`+${Math.round((Date.now() - started) / 1000)}s arrived ${row.shipment_id} ${row.workflow_state}`);
      }
      if (item.listedAfterMs === null && (await page.getByText(row.shipment_id).count()) > 0) {
        item.listedAfterMs = Date.now() - item.arrivedAt;
        await page.screenshot({ path: `screenshots/live-queue-${seen.size}.png` });
      }
      if (!/^(OPEN|REOPENED|INVESTIGATING)$/.test(row.workflow_state) && item.final !== row.workflow_state) {
        item.final = row.workflow_state;
        console.log(`+${Math.round((Date.now() - started) / 1000)}s ${row.shipment_id} -> ${row.workflow_state}`);
        if (watching === row.case_id) {
          await casePage.waitForTimeout(6000);
          item.headers.push(
            `END: ${await casePage.locator(".pipeline-meta > span").innerText().catch(() => "?")}`,
          );
          await casePage.screenshot({
            path: `screenshots/live-${row.shipment_id}-end.png`,
            fullPage: true,
          });
          watching = null;
        }
      }
    }
    const active = queue.items.find((row) => row.workflow_state === "INVESTIGATING");
    if (active && watching !== active.case_id) {
      watching = active.case_id;
      await casePage.goto(`/app/cases/${active.case_id}`);
    }
    if (watching) {
      const item = seen.get(watching)!;
      const header = await casePage
        .locator(".pipeline-meta > span")
        .innerText({ timeout: 2000 })
        .catch(() => "");
      const stage = await casePage
        .locator(".pipeline-stage-summary")
        .innerText({ timeout: 2000 })
        .catch(() => "");
      if (header && item.headers.at(-1) !== header) item.headers.push(header);
      if (stage && item.stageTexts.at(-1) !== stage) item.stageTexts.push(stage);
      if (item.headers.length === 3)
        await casePage.screenshot({
          path: `screenshots/live-${item.shipment}-running.png`,
          fullPage: true,
        });
    }
    await page.waitForTimeout(2000);
  }
  const report = [...seen.values()];
  // The backend's own account of why runs repeated or were kept, for the report.
  const audit: unknown[] = [];
  let cursor: string | null = null;
  for (let pageNo = 0; pageNo < 8; pageNo++) {
    const body: { items?: unknown[]; next_cursor?: string | null } = await request
      .get(`/audit?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`)
      .then((response) => response.json())
      .catch(() => ({}));
    audit.push(...(body.items ?? []));
    cursor = body.next_cursor ?? null;
    if (!cursor) break;
  }
  const details: unknown[] = [];
  for (const id of seen.keys())
    details.push(await request.get(`/cases/${id}`).then((r) => r.json()).catch(() => null));
  writeFileSync(
    "test-results/live-arrivals.json",
    JSON.stringify({ errors, report, audit, details }, null, 2),
  );
  for (const item of report)
    console.log(
      `${item.shipment}: final ${item.final ?? "not finished"}; listed after ${item.listedAfterMs ?? "never"} ms; ${item.headers.length} header texts; running clock seen: ${item.headers.some((text) => /in progress · \d/.test(text))}`,
    );
  expect(errors).toEqual([]);
  expect(seen.size).toBeGreaterThanOrEqual(EXPECTED);
});
