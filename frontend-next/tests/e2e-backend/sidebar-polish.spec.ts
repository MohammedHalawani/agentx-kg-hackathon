import { test, expect, type Page, type Locator } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { stubBackend } from "./backend-stub";
import {
  CASE_A,
  CASE_B,
  SHIP_A,
  page as pageOf,
  queueRows,
} from "../fixtures/backend";
import type { ApiQueueCase } from "../../src/api/contracts";

const captures = "../artifacts/final-sidebar-polish/screenshots";
mkdirSync(captures, { recursive: true });
function queue(waiting: number, closed: number, open = 12): ApiQueueCase[] {
  return [
    ...Array.from({ length: waiting }, (_, index) => ({
      ...queueRows[0],
      case_id: index ? `SYN-POLISH-WAIT-${index}` : CASE_A,
      shipment_id: index ? `SYN-POLISH-WAIT-SHIP-${index}` : SHIP_A,
    })),
    ...Array.from({ length: closed }, (_, index) => ({
      ...queueRows[1],
      case_id: index ? `SYN-POLISH-CLOSED-${index}` : CASE_B,
      shipment_id: index
        ? `SYN-POLISH-CLOSED-SHIP-${index}`
        : queueRows[1].shipment_id,
    })),
    ...Array.from({ length: open }, (_, index) => ({
      ...queueRows[2],
      case_id: `SYN-POLISH-OPEN-${index}`,
      shipment_id: `SYN-POLISH-OPEN-SHIP-${index}`,
    })),
  ];
}
async function openPanel(page: Page) {
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  return page.getByRole("complementary", { name: "Waiting and closed cases" });
}
async function geometry(panel: Locator) {
  const card = (await panel.boundingBox())!;
  const list = (await panel.getByRole("tabpanel").boundingBox())!;
  const pager = (await panel.getByRole("navigation").boundingBox())!;
  const summary = (await panel.locator(".rail-summary").boundingBox())!;
  const history = (await panel.locator(".rail-history").boundingBox())!;
  expect(pager.y - (list.y + list.height)).toBeLessThanOrEqual(1);
  expect(summary.y - (pager.y + pager.height)).toBeLessThanOrEqual(1);
  expect(history.y - (summary.y + summary.height)).toBeLessThanOrEqual(8);
  expect(card.y + card.height - history.y - history.height).toBeLessThanOrEqual(
    16,
  );
  return { card, list, pager, summary, history };
}

for (const count of [0, 1, 4, 5, 52]) {
  test(`${count} Waiting cases use intrinsic height, four-row pages and full loaded counts`, async ({
    page,
  }) => {
    const stub = await stubBackend(page);
    stub.state.queue = queue(count, count ? 2 : 0);
    const panel = await openPanel(page);
    await expect(panel.getByRole("tab", { name: /^Waiting/ })).toContainText(
      String(count),
    );
    await expect(panel.locator(".resolved-entry")).toHaveCount(
      Math.min(4, count),
    );
    const pager = panel.getByRole("navigation");
    await expect(pager).toContainText(
      `Showing ${count ? 1 : 0}–${Math.min(4, count)} of ${count}`,
    );
    await expect(
      pager.getByRole("button", { name: "Previous case queue page" }),
    ).toBeDisabled();
    if (count > 4)
      await expect(
        pager.getByRole("button", { name: "Next case queue page" }),
      ).toBeEnabled();
    else
      await expect(
        pager.getByRole("button", { name: "Next case queue page" }),
      ).toBeDisabled();
    await expect(
      panel
        .locator(".rail-summary > div")
        .filter({ hasText: "Human attention" }),
    ).toContainText(String(count));
    const bounds = await geometry(panel);
    if (count < 2) {
      expect(bounds.card.height).toBeLessThan(count ? 450 : 350);
      const ledger = (await page.locator(".operations-ledger").boundingBox())!;
      expect(bounds.card.height).toBeLessThan(ledger.height - 120);
    }
    await panel.getByRole("link", { name: "Resolution history" }).click();
    await expect(page).toHaveURL(/\/audit\?kind=resolution$/);
    expect(stub.posts).toEqual([]);
  });
}

test("Waiting and Closed preserve independent positions and clamp persisted indices after additions and removals", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.queue = queue(9, 6);
  const panel = await openPanel(page);
  const pager = panel.getByRole("navigation");
  const next = pager.getByRole("button", { name: "Next case queue page" });
  await next.click();
  await next.click();
  await expect(pager).toContainText("Showing 9–9 of 9");
  await panel.getByRole("tab", { name: /^Closed/ }).click();
  await expect(pager).toContainText("Showing 1–4 of 6");
  await next.click();
  await expect(pager).toContainText("Showing 5–6 of 6");
  await panel.getByRole("tab", { name: /^Waiting/ }).click();
  await expect(pager).toContainText("Showing 9–9 of 9");
  stub.state.queue = queue(10, 6);
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(pager).toContainText("Showing 9–10 of 10");
  const focused = panel.getByRole("tabpanel").getByRole("link").first();
  const href = await focused.getAttribute("href");
  await focused.focus();
  // A real poll replaces record objects; keyed links must preserve focus and identity.
  const polled = page.waitForResponse(
    (response) => new URL(response.url()).pathname === "/cases/queue",
  );
  await polled;
  await expect(focused).toBeFocused();
  await expect(focused).toHaveAttribute("href", href!);
  stub.state.queue = queue(4, 6);
  // The production poll interval is five seconds; allow two cycles plus response/render time.
  await expect(pager).toContainText("Showing 1–4 of 4", { timeout: 15000 });
  await expect(
    panel.getByRole("tabpanel").getByRole("link").first(),
  ).toBeFocused();
  await expect(pager.locator(".case-queue-page-index")).toHaveText("1 / 1");
  stub.state.queue = queue(5, 6);
  await page.getByRole("button", { name: "Refresh queue" }).click();
  await expect(pager).toContainText("Showing 1–4 of 5");
  await panel.getByRole("tab", { name: /^Closed/ }).click();
  await expect(pager).toContainText("Showing 5–6 of 6");
  await expect(panel.getByTestId("resolution-pending-count")).toContainText(
    "1 verified",
  );
  await expect(panel.locator(".verified-check")).toHaveCount(0); // Verification belongs to the full collection, not this visible page.
  expect(stub.posts).toEqual([]);
});

test("cursor-bounded queue reports only loaded pages and does not imply unavailable server totals", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const cursors = { active: new Set<number>(), resolved: new Set<number>() };
  await page.route("**/cases/queue?**", (route) => {
    const url = new URL(route.request().url());
    const scope =
      url.searchParams.get("scope") === "resolved" ? "resolved" : "active";
    const offset = Number(url.searchParams.get("cursor") ?? 0);
    cursors[scope].add(offset);
    const row =
      scope === "active"
        ? {
            ...queueRows[0],
            case_id: `SYN-CURSOR-WAIT-${offset}`,
            shipment_id: `SYN-CURSOR-WAIT-SHIP-${offset}`,
          }
        : {
            ...queueRows[1],
            case_id: `SYN-CURSOR-CLOSED-${offset}`,
            shipment_id: `SYN-CURSOR-CLOSED-SHIP-${offset}`,
          };
    return route.fulfill({
      json: { ...pageOf([row], String(offset + 1)), filtered_total: 5000 },
    });
  });
  const panel = await openPanel(page);
  await expect(panel.getByTestId("case-queue-subset")).toContainText(
    "Counts below describe loaded records",
  );
  await expect(panel.getByRole("tab", { name: /^Waiting/ })).toContainText(
    "10",
  );
  await expect(panel.getByRole("tab", { name: /^Closed/ })).toContainText("10");
  const pager = panel.getByRole("navigation");
  await expect(pager).toContainText("Showing 1–4 of 10 loaded");
  const next = pager.getByRole("button", { name: "Next case queue page" });
  await next.click();
  await next.click();
  await expect(pager).toContainText("Showing 9–10 of 10 loaded");
  await expect(pager.locator(".case-queue-page-index")).toHaveText("3 / 3");
  await expect(next).toBeDisabled();
  await expect(panel.locator(".resolved-entry")).toHaveCount(2);
  expect([...cursors.active]).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  expect([...cursors.resolved]).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);
  expect(stub.posts).toEqual([]);
});

test("only the header badge is removed; readable demo provenance remains visible through scrolling", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.queue = queue(1, 2, 52);
  await page.goto("/app/operations");
  await expect(page.locator("header .synthetic-data-label")).toHaveCount(0);
  await expect(page.locator(".environment-badge")).toHaveText("Connected");
  await expect(page.locator(".environment-badge")).toHaveAttribute(
    "data-dataset",
    "synthetic",
  );
  await page.getByRole("combobox", { name: "Rows per page" }).click();
  await page.getByRole("option", { name: "50", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(50);
  for (const position of [0, 500, 1500]) {
    await page.evaluate((top) => window.scrollTo(0, top), position);
    const disclosure = page.getByTestId("demo-provenance");
    await expect(disclosure).toContainText(
      "demonstration data, not SPL systems",
    );
    await expect(disclosure).toBeInViewport();
    expect(
      await disclosure.evaluate((e) =>
        parseFloat(getComputedStyle(e).fontSize),
      ),
    ).toBeGreaterThanOrEqual(10);
  }
  expect(stub.posts).toEqual([]);
});

test("Arabic mini-pagination supports keyboard tabs and reduced motion", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.queue = queue(6, 6);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() =>
    localStorage.setItem(
      "suhail-ui-lab.preferences",
      JSON.stringify({ theme: "light", language: "ar", motion: "reduce" }),
    ),
  );
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  const panel = page.getByRole("complementary", {
    name: "Waiting and closed cases",
  });
  const waiting = panel.getByRole("tab", { name: /المنتظرة/ });
  const closed = panel.getByRole("tab", { name: /المغلقة/ });
  await waiting.focus();
  await page.keyboard.press("End");
  await expect(closed).toBeFocused();
  await expect(closed).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(waiting).toBeFocused();
  const next = panel.getByRole("button", { name: "الصفحة التالية للحالات" });
  await next.focus();
  await page.keyboard.press("Space");
  await expect(panel.locator(".case-queue-page-index")).toHaveText("2 / 2");
  await expect(next).toBeDisabled();
  expect(
    await next.locator("svg").evaluate((e) => getComputedStyle(e).transform),
  ).toBe("matrix(-1, 0, 0, -1, 0, 0)");
  expect(
    await panel
      .getByRole("tabpanel")
      .evaluate((e) => getComputedStyle(e).animationName),
  ).toBe("none");
  await expect(page.getByTestId("demo-provenance")).toContainText(
    "بيانات تجريبية",
  );
  expect(stub.posts).toEqual([]);
});

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
]) {
  test(`Operations queue captures and measured intrinsic dimensions at ${viewport.width}x${viewport.height}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    const stub = await stubBackend(page);
    const measurements: Record<string, unknown> = { viewport };
    for (const scenario of [
      "one-waiting",
      "multiple-waiting",
      "closed",
    ] as const) {
      stub.state.queue = queue(
        scenario === "one-waiting" ? 1 : 6,
        scenario === "closed" ? 52 : 2,
      );
      const panel = await openPanel(page);
      if (scenario === "closed")
        await panel.getByRole("tab", { name: /^Closed/ }).click();
      await expect(panel.locator(".resolved-entry")).toHaveCount(
        scenario === "one-waiting" ? 1 : 4,
      );
      if (scenario === "closed")
        await expect(
          panel.getByTestId("resolution-pending-count"),
        ).toContainText("1 verified");
      for (const state of ["expanded", "collapsed"]) {
        const sidebar = page.locator('[data-slot="sidebar"][data-state]');
        if ((await sidebar.getAttribute("data-state")) !== state)
          await page.getByRole("button", { name: "Toggle Sidebar" }).click();
        await expect(sidebar).toHaveAttribute("data-state", state);
        await page.waitForTimeout(220); // Existing nav width transition, before geometry/capture.
        const measured = await geometry(panel);
        measurements[`${scenario}-${state}`] = measured;
        await expect(page.getByTestId("demo-provenance")).toBeInViewport();
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth),
        ).toBeLessThanOrEqual(viewport.width);
        await page.screenshot({
          path: `${captures}/${scenario}-${state}-${viewport.width}x${viewport.height}.png`,
        });
      }
    }
    writeFileSync(
      `${captures}/metrics-${viewport.width}x${viewport.height}.json`,
      JSON.stringify(measurements, null, 2),
    );
    expect(stub.posts).toEqual([]);
  });
}
