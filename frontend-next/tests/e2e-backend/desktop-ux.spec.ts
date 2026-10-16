import { test, expect, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { stubBackend } from "./backend-stub";
import {
  CASE_A,
  CASE_C,
  SHIP_A,
  workerStatusDual,
  queueRows,
  page as pageOf,
} from "../fixtures/backend";
import type { ApiWorkerStatus } from "../../src/api/contracts";

const captures = "../artifacts/desktop-ux/screenshots";
mkdirSync(captures, { recursive: true });
async function select(page: Page, label: string, option: string) {
  const control = page.getByRole("combobox", { name: label, exact: true });
  await control.click();
  await page.getByRole("option", { name: option, exact: true }).click();
  await expect(control).toContainText(option);
}
async function roster(page: Page, source: ApiWorkerStatus) {
  await page.route("**/worker/status", (route) =>
    route.fulfill({ json: source }),
  );
}

test("worker navigation uses actual assignments, keyboard tooltips, release and reassignment without starting work", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const source = structuredClone(workerStatusDual);
  // Pausing new auto work does not stop an already RUNNING investigation.
  source.worker.state = "paused";
  await roster(page, source);
  await page.goto("/app/operations");
  const workers = page.getByTestId("working-agents");
  await expect(workers.getByRole("link")).toHaveCount(2);
  const a = page.getByTestId(`worker-case-${CASE_A}`);
  await expect(a).toHaveAttribute("data-running", "true");
  await a.focus();
  await expect(page.getByRole("tooltip")).toContainText("investigation-1");
  await expect(page.getByRole("tooltip")).toContainText(SHIP_A);
  await expect(page.getByRole("tooltip")).toContainText("Review");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(CASE_A));
  await expect(a).toHaveAttribute("aria-current", "page");
  await expect(
    page.locator('[data-slot="sidebar"][data-state]'),
  ).toHaveAttribute("data-state", "collapsed");
  await page.getByRole("button", { name: "Toggle Sidebar" }).click();
  await page.getByTestId(`worker-case-${CASE_C}`).click();
  await expect(page).toHaveURL(new RegExp(CASE_C));
  // Switching assignments preserves the operator's expanded navigation choice.
  await expect(
    page.locator('[data-slot="sidebar"][data-state]'),
  ).toHaveAttribute("data-state", "expanded");
  const snapshot = source.worker.active_cases![0];
  source.worker.active_cases = [source.worker.active_cases![1]];
  source.worker.active_count = 1;
  await expect(a).toHaveCount(0, { timeout: 15000 });
  await expect(page.getByTestId("worker-capacity")).toContainText(
    "1 available",
  );
  source.worker.active_cases = [
    {
      ...snapshot,
      case_id: CASE_A,
      worker_id: "investigation-2",
      active_stage: "retrieve_context",
      run_status: "FAILED",
    },
  ];
  await expect(a).toHaveAttribute("aria-label", /investigation-2/, {
    timeout: 15000,
  });
  await expect(a).toHaveAttribute("data-running", "false");
  source.worker.active_cases = [];
  source.worker.active_count = 0;
  await expect(workers.getByRole("link")).toHaveCount(0, { timeout: 15000 });
  await expect(page.getByTestId("worker-capacity")).toContainText(
    "2 available",
  );
  expect(stub.posts).toEqual([]);
});

test("several workers are bounded and paged; offline and reduced motion stop liveness animation", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  const source = structuredClone(workerStatusDual);
  source.worker.concurrency = 16;
  source.worker.active_count = 15;
  source.worker.active_cases = Array.from({ length: 15 }, (_, index) => ({
    ...workerStatusDual.worker.active_cases![0],
    case_id: `SYN-EXTRA-${index}`,
    worker_id: `investigation-${index + 1}`,
    run_status: index === 2 ? "FAILED" : "RUNNING",
  }));
  await roster(page, source);
  await page.goto("/app/operations");
  const workers = page.getByTestId("working-agents");
  await expect(workers.getByRole("link")).toHaveCount(12);
  await expect(workers).toHaveAttribute("data-reduced-motion", "true");
  await expect(page.getByTestId("worker-case-SYN-EXTRA-2")).toHaveAttribute(
    "data-running",
    "false",
  );
  expect(
    await workers
      .locator(".worker-activity i")
      .first()
      .evaluate((e) => getComputedStyle(e).animationName),
  ).toBe("none");
  await page.getByRole("button", { name: "Next worker page" }).click();
  await expect(workers.getByRole("link")).toHaveCount(3);
  await page.getByRole("button", { name: "Toggle Sidebar" }).click();
  const tile = workers.getByRole("link").first();
  expect((await tile.boundingBox())!.width).toBeLessThan(40);
  await tile.focus();
  await expect(page.getByRole("tooltip")).toContainText("SYN-SHP");
  stub.state.online = false;
  await expect(page.getByTestId("worker-capacity")).toHaveAttribute(
    "aria-label",
    "Worker status unavailable",
    { timeout: 15000 },
  );
  await expect(tile).toHaveAttribute("data-running", "false");
  expect(stub.posts).toEqual([]);
});

test("drawer drafts, apply, individual reset and honest loaded-page numbers retain access to every collection", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const extra = Array.from({ length: 62 }, (_, index) => ({
    ...queueRows[2],
    case_id: `SYN-OPEN-${index}`,
    shipment_id: `SYN-OPEN-SHIP-${index}`,
  }));
  stub.state.queue = [...queueRows, ...extra];
  let queuePages = 0;
  await page.route("**/cases/queue?**", (route) => {
    const url = new URL(route.request().url());
    const rows = stub.state.queue.filter(
      (row) =>
        (url.searchParams.get("scope") === "resolved") ===
        (row.workflow_state === "RESOLVED"),
    );
    const offset = Number(url.searchParams.get("cursor") ?? 0);
    const next = offset + 20 < rows.length ? String(offset + 20) : null;
    queuePages++;
    return route.fulfill({
      json: {
        ...pageOf(rows.slice(offset, offset + 20)),
        next_cursor: next,
        total: rows.length,
      },
    });
  });
  await page.goto("/app/operations");
  await expect(
    page.getByText("Showing 1–10 of 63", { exact: true }),
  ).toBeVisible();
  expect(queuePages).toBeGreaterThanOrEqual(5);
  await page.getByRole("button", { name: "Table page 7", exact: true }).click();
  await expect(
    page.getByText("Showing 61–63 of 63", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Next table page" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: /^Filters/ }).click();
  await select(page, "Case collection", "All loaded cases");
  await select(page, "Filter by priority", "High");
  await page.keyboard.press("Escape");
  await expect(
    page.getByText("Showing 61–63 of 63", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Filters/ }).click();
  await expect(
    page.getByRole("combobox", { name: "Case collection", exact: true }),
  ).toContainText("Unassigned candidates");
  await select(page, "Case collection", "All loaded cases");
  await select(page, "Filter by priority", "High");
  await page
    .getByRole("button", { name: "Apply filters", exact: true })
    .click();
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toBeVisible();
  await page
    .getByRole("button", { name: "Remove Filter by priority", exact: true })
    .click();
  await expect(
    page.getByRole("button", {
      name: "Remove Filter by priority",
      exact: true,
    }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: /^Filters/ }).click();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toHaveCount(0);
  await page
    .getByRole("textbox", { name: "Search exception queue" })
    .fill(SHIP_A);
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toBeVisible();
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(page.getByRole("tabpanel")).toContainText(SHIP_A);
  await page.getByRole("tab", { name: /^Closed/ }).click();
  await expect(page.getByTestId("resolution-pending-count")).toContainText(
    "1 verified",
  );
  // Manual/cursor tables keep previous/next navigation, without invented random access.
  await page.goto("/app/audit");
  await expect(page.getByTestId("audit-event-count")).toHaveText("4");
  await expect(page.getByRole("button", {name: /^Table page \d/})).toHaveCount(0);
  await expect(page.getByRole("button", {name: "Next table page"})).toBeVisible();
  expect(stub.posts).toEqual([]);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`desktop captures and overlay/canvas checks at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const stub = await stubBackend(page);
    stub.state.dualWorker = true;
    // Scripted queue rows exercise density; this is UI QA, not live dataset evidence.
    stub.state.queue.push(
      ...Array.from({ length: 8 }, (_, index) => ({
        ...queueRows[index % 2 === 0 ? 0 : 2],
        case_id: `SYN-UX-OPEN-${index}`,
        shipment_id: `SYN-SHP-UX-${String(index + 1).padStart(3, "0")}`,
        workflow_state: "OPEN" as const,
      })),
    );
    stub.state.queue.push({
      ...queueRows[0],
      case_id: "SYN-UX-WAITING",
      shipment_id: "SYN-SHP-UX-WAITING",
    });
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const measurements: Record<string, unknown> = { viewport };
    for (const screen of ["operations", "investigation"]) {
      await page.goto(
        screen === "operations" ? "/app/operations" : `/app/cases/${CASE_A}`,
      );
      if (screen === "operations") {
        await expect(page.locator("tbody tr")).toHaveCount(8);
        await page
          .getByRole("button", { name: "Expand resolved panel" })
          .click();
      } else
        await expect(
          page.getByTestId("knowledge-graph").locator(".entity-node").first(),
        ).toBeVisible();
      // Dismiss transient state-change notifications through their actual close controls.
      for (const close of await page
        .locator("[data-sonner-toast] [data-close-button]")
        .all())
        if (await close.isVisible()) await close.click();
      for (const state of ["expanded", "collapsed"]) {
        const sidebar = page.locator('[data-slot="sidebar"][data-state]');
        if ((await sidebar.getAttribute("data-state")) !== state)
          await page.getByRole("button", { name: "Toggle Sidebar" }).click();
        await expect(sidebar).toHaveAttribute("data-state", state);
        await page.waitForTimeout(220); // Let the existing 200 ms nav resize finish before measuring/capturing.
        await expect
          .poll(() =>
            page.evaluate(
              () => document.documentElement.scrollWidth <= innerWidth + 1,
            ),
          )
          .toBe(true);
        if (screen === "investigation") {
          await expect
            .poll(
              async () =>
                (await page.getByTestId("route-map").boundingBox())!.height,
            )
            .toBeGreaterThanOrEqual(400);
          const map = (await page.getByTestId("route-map").boundingBox())!;
          const graph = (await page
            .getByTestId("knowledge-graph")
            .boundingBox())!;
          expect(graph.height).toBeGreaterThanOrEqual(400);
          expect(map.width).toBeGreaterThan(300);
          expect(graph.width).toBeGreaterThan(300);
          measurements[state] = { map, graph };
        } else {
          const controls = await page.locator(".queue-controls").boundingBox();
          expect(controls!.x + controls!.width).toBeLessThan(viewport.width);
        }
        await page.screenshot({
          path: `${captures}/${screen}-${state}-${viewport.width}x${viewport.height}.png`,
          fullPage: false,
        });
      }
    }
    // A real UI notification triggered by a scripted read. It stays above the evidence area.
    await page.goto("/app/operations");
    await page.getByRole("button", { name: "Refresh queue" }).click();
    const toast = page.locator("[data-sonner-toast]").filter({hasText: "Queue read from the backend"}).first();
    await expect(toast).toContainText("Queue read from the backend");
    await page.getByTestId(`worker-case-${CASE_A}`).click();
    await expect(page.getByTestId("knowledge-graph")).toBeVisible();
    const toastBounds = (await toast.boundingBox())!;
    const graphBounds = (await page
      .getByTestId("knowledge-graph")
      .boundingBox())!;
    expect(toastBounds.y + toastBounds.height).toBeLessThan(graphBounds.y);
    measurements.toast = toastBounds;
    writeFileSync(
      `${captures}/metrics-${viewport.width}x${viewport.height}.json`,
      JSON.stringify(measurements, null, 2),
    );
    expect(errors).toEqual([]);
    expect(stub.posts).toEqual([]);
  });
}
