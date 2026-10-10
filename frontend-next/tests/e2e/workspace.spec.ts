import { test, expect, type Page } from "@playwright/test";

const errors = new WeakMap<Page, string[]>();
test.beforeEach(async ({ page }) => {
  const collected: string[] = [];
  errors.set(page, collected);
  page.on("pageerror", (error) => collected.push(error.message));
  await page.addInitScript(() => {
    if (!localStorage.getItem("suhail-ui-lab.preferences"))
      localStorage.setItem(
        "suhail-ui-lab.preferences",
        JSON.stringify({
          theme: "light",
          language: "en",
          motion: "reduce",
          density: "comfortable",
        }),
      );
  });
});
test.afterEach(async ({ page }) => {
  expect(errors.get(page), "No uncaught application errors").toEqual([]);
});

async function choose(page: Page, label: string, option: string) {
  await page.getByRole("combobox", { name: label, exact: true }).click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
async function openChat(page: Page) {
  await page
    .getByRole("button", { name: "Ask Suhail", exact: true })
    .first()
    .click();
  await expect(
    page.getByRole("dialog", { name: "Canopus", exact: true }),
  ).toBeVisible();
}
async function sendHelper(page: Page, request: string) {
  await page.getByRole("textbox", { name: "Ask Canopus" }).fill(request);
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(
    page.getByRole("textbox", { name: "Ask Canopus" }),
  ).toBeEnabled();
}
async function settlePausedWorkspace(page: Page, heading: string) {
  // React's lazy-route fallback needs browser frames even while the demo clock is held.
  await expect
    .poll(
      async () => {
        await page.clock.runFor(100);
        return page
          .getByRole("heading", { name: heading, exact: true, level: 1 })
          .isVisible();
      },
      { timeout: 10000 },
    )
    .toBe(true);
  await page.clock.runFor(100);
}
async function waitForGraphFit(page: Page) {
  await expect
    .poll(
      () =>
        page.getByTestId("knowledge-graph").evaluate((canvas) => {
          const bounds = canvas.getBoundingClientRect();
          const nodes = [...canvas.querySelectorAll(".react-flow__node")];
          return (
            nodes.length > 0 &&
            nodes.every((node) => {
              const rect = node.getBoundingClientRect();
              return (
                rect.left >= bounds.left - 1 &&
                rect.right <= bounds.right + 1 &&
                rect.top >= bounds.top - 1 &&
                rect.bottom <= bounds.bottom + 1
              );
            })
          );
        }),
      { message: "The default graph fits after the canvas resizes" },
    )
    .toBe(true);
}

test("Operations filters, pagination, resolved rail, and navigation", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Operations", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Showing 1–10 of 12", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Next table page" }).click();
  await expect(
    page.getByText("Showing 11–12 of 12", { exact: true }),
  ).toBeVisible();
  await choose(page, "Sort cases", "Oldest first");
  await expect(page.locator("tbody tr").first()).toContainText("SHP-10433");
  await choose(page, "Filter by city", "Khobar");
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await page
    .getByRole("textbox", { name: "Search exception queue" })
    .fill("no-such-shipment");
  await expect(
    page.getByText("No matching exceptions", { exact: true }),
  ).toBeVisible();
  await page.getByRole("textbox", { name: "Search exception queue" }).fill("");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(
    page.getByRole("complementary", { name: "Verified resolutions" }),
  ).toContainText("SHP-10453");
  await page.getByRole("button", { name: "Collapse resolved panel" }).click();
  await page.getByRole("link", { name: "SHP-10498", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "SHP-10498", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "SHP-10498", exact: true }),
  ).toBeVisible();
});

test("Investigation keeps linked map and graph side by side on desktop and laptop", async ({
  page,
}) => {
  await page.goto("/cases/SHP-10482");
  await expect(
    page.getByRole("heading", { name: "SHP-10482", exact: true }),
  ).toBeVisible();
  for (const width of [1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    const map = page.getByTestId("route-map");
    const graph = page.getByTestId("knowledge-graph");
    await expect(map).toBeVisible();
    await expect(graph).toBeVisible();
    await expect
      .poll(
        async () => {
          const m = await map.boundingBox(),
            g = await graph.boundingBox();
          return (
            !!m &&
            !!g &&
            Math.abs(m.y - g.y) < 3 &&
            m.width > 280 &&
            g.width > 280 &&
            m.height > 300 &&
            g.x > m.x
          );
        },
        { message: `Both evidence canvases usable at ${width}px` },
      )
      .toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("group", {
      name: "Contractor vehicle position · observation",
      exact: true,
    })
    .click();
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "vehicle position only",
  );
  await expect(page.locator(".evidence-marker.selected")).toHaveCount(1);
  await page.getByRole("button", { name: "Tree", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Tree", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Map focus", exact: true }).click();
  await expect
    .poll(
      async () =>
        (await page.getByTestId("route-map").boundingBox())!.width /
        (await page.getByTestId("knowledge-graph").boundingBox())!.width,
    )
    .toBeGreaterThan(1.3);
  await page.getByRole("button", { name: "Balanced view" }).click();
  await expect(
    page.getByRole("button", { name: "Balanced view" }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Map layers", exact: true }).click();
  await choose(page, "Base map", "Offline schematic");
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("route-map")).toContainText(
    "Offline schematic",
  );
  await page.getByRole("button", { name: "Collect · completed" }).click();
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "Origin custody confirmed",
  );
});

test("Case chat has keyboard mentions, grounded participant replies, and persistent collapse", async ({
  page,
}) => {
  await page.goto("/cases/SHP-10482");
  await openChat(page);
  const editor = page.getByRole("textbox", {
    name: "Ask Canopus",
  });
  await editor.fill("@rev");
  await expect(page.getByRole("option", { name: /@reviewer/ })).toBeVisible();
  await editor.press("ArrowDown");
  await page
    .getByRole("combobox", { name: "Find assistant mention" })
    .press("Enter");
  await expect(editor).toHaveValue("@reviewer ");
  await editor.fill("@reviewer why is approval required?");
  await editor.press("Enter");
  const transcript = page.getByRole("region", {
    name: "Canopus conversation transcript",
  });
  await expect(transcript).toContainText("policy C-04");
  await expect(transcript).toContainText("Confirmed parcel custody at Al Ahsa");
  await expect(transcript.locator("time")).toHaveCount(2);
  await page
    .getByRole("button", { name: "Minimize Canopus conversation" })
    .click();
  await expect(transcript).not.toBeVisible();
  await openChat(page);
  await expect(transcript).toContainText("policy C-04");
  await expect(transcript).toContainText("Awaiting human decision");
  await page
    .getByRole("button", { name: "Minimize Canopus conversation", exact: true })
    .click();
  await page
    .getByRole("group", {
      name: "Contractor vehicle position · observation",
      exact: true,
    })
    .click();
  await openChat(page);
  await editor.fill("@investigator explain the highlighted node");
  await editor.press("Enter");
  await expect(transcript).toContainText("Confirms vehicle position only");
  await expect(transcript).toContainText("Investigator");
});

test("Long conversations support keyboard reading and jump to latest without forced scrolling", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const rows = Array.from({ length: 24 }, (_, i) => ({
      id: `history-${i}`,
      role: i % 2 ? "assistant" : "user",
      agent: "suhail",
      text: `Historical exchange ${i + 1}. Parcel-level observations establish custody. Vehicle location is separate telemetry.`,
      timestamp: "2026-10-09T10:00:00+03:00",
    }));
    sessionStorage.setItem(
      "suhail-ui-lab.chat",
      JSON.stringify({ "SHP-10482": rows }),
    );
  });
  await page.goto("/cases/SHP-10482");
  await openChat(page);
  const viewport = page.getByRole("region", {
    name: "Canopus conversation transcript",
  });
  await expect
    .poll(() =>
      viewport.evaluate((el) => el.scrollHeight > el.clientHeight * 5),
    )
    .toBe(true);
  await viewport.focus();
  await viewport.press("Control+Home");
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollTop))
    .toBeLessThan(100);
  const latest = page.getByRole("button", { name: "Jump to latest" });
  await expect(latest).toHaveAttribute("data-active", "true");
  await latest.click();
  await expect
    .poll(() =>
      viewport.evaluate(
        (el) => el.scrollHeight - el.scrollTop - el.clientHeight,
      ),
    )
    .toBeLessThan(60);
  const editor = page.getByRole("textbox", {
    name: "Ask Canopus",
  });
  await editor.fill("@suhail where is confirmed custody?");
  await editor.press("Enter");
  await viewport.hover();
  await page.mouse.wheel(0, -9000);
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollTop / el.scrollHeight))
    .toBeLessThan(0.3);
  await expect(viewport).toContainText("Last confirmed parcel custody:");
  await expect
    .poll(() => viewport.evaluate((el) => el.scrollTop / el.scrollHeight))
    .toBeLessThan(0.3);
  await expect(latest).toHaveAttribute("data-active", "true");
});

test("Human approval authorizes execution, and only verified outcome moves to Resolved", async ({
  page,
}) => {
  // Hold the demo clock during navigation, then observe each required transition.
  await page.clock.install({ time: new Date("2026-10-09T12:00:00+03:00") });
  await page.clock.pauseAt(new Date("2026-10-09T12:00:10+03:00"));
  await page.goto("/cases/SHP-10482");
  await settlePausedWorkspace(page, "SHP-10482");
  await page
    .getByRole("button", { name: "Review & authorize", exact: true })
    .click();
  const dialog = page.getByRole("dialog", { name: "Authorize this action" });
  await expect(
    dialog.getByRole("button", { name: "Authorize action" }),
  ).toBeDisabled();
  await dialog
    .getByRole("textbox", { name: "Decision reason" })
    .fill(
      "Authorize reconciliation using the independent Al Ahsa parcel scan.",
    );
  await dialog.getByRole("button", { name: "Authorize action" }).click();
  await page.clock.runFor(50);
  await expect(page.locator(".case-heading")).toContainText("Executing");
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]'),
  ).toHaveCount(0);
  await page
    .getByRole("link", { name: "Operations", exact: true })
    .first()
    .click();
  await expect(page).toHaveURL(/\/operations$/);
  await page.clock.runFor(50);
  await page
    .getByRole("textbox", { name: "Search exception queue" })
    .fill("SHP-10482");
  await page.clock.runFor(50);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText("SHP-10482");
  await page.clock.runFor(2400);
  await expect(page.locator("tbody")).toContainText("Verifying", {
    timeout: 6000,
  });
  await page.clock.runFor(2400);
  await expect(page.locator("tbody tr")).toHaveCount(0, { timeout: 6000 });
  const toast = page.locator('[data-sonner-toast][data-type="success"]');
  await expect(toast).toContainText("SHP-10482 resolved — outcome verified");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(
    page.getByRole("complementary", { name: "Verified resolutions" }),
  ).toContainText("SHP-10482");
  await toast.getByRole("button", { name: "Open case", exact: true }).click();
  await page.clock.runFor(50);
  await expect(
    page.getByRole("heading", { name: "SHP-10482", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".case-heading")).toContainText("Resolved");
});

test("Automatic investigation progresses one FIFO case and finishes after pause", async ({
  page,
}) => {
  // Allow the complete seven-stage visual sequence on a busy desktop host.
  test.setTimeout(90000);
  await page.clock.install({ time: new Date("2026-10-09T12:00:00+03:00") });
  await page.clock.pauseAt(new Date("2026-10-09T12:00:10+03:00"));
  await page.goto("/cases/SHP-10471");
  await settlePausedWorkspace(page, "SHP-10471");
  await page
    .getByRole("link", { name: "Operations", exact: true })
    .first()
    .click();
  await page.clock.runFor(50);
  await choose(page, "Sort cases", "Oldest first");
  await page.getByRole("switch", { name: "Automatic investigation" }).click();
  await page.clock.runFor(2400);
  await expect(
    page.locator('tr[data-testid="data-row-SHP-10471"]'),
  ).toContainText("Investigating");
  await page.getByRole("switch", { name: "Automatic investigation" }).click();
  await page.getByRole("link", { name: "SHP-10471", exact: true }).click();
  await page.clock.runFor(50);
  await openChat(page);
  await page.clock.runFor(50);
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Investigation started");
  for (let i = 0; i < 7; i++) await page.clock.runFor(2400);
  await expect(page.locator(".case-heading")).toContainText("Resolved");
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Outcome independently verified");
  await page
    .getByRole("link", { name: "Operations", exact: true })
    .first()
    .click();
  await expect(
    page.locator('tr[data-testid="data-row-SHP-10487"]'),
  ).toContainText("Queued");
  await expect(
    page.getByRole("switch", { name: "Automatic investigation" }),
  ).not.toBeChecked();
});

test("Reject and escalation dialogs preserve authority history and unresolved status", async ({
  page,
}) => {
  await page.goto("/decisions");
  await page
    .getByRole("button", { name: "Review SHP-10479", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Reject / request evidence", exact: true })
    .click();
  await page
    .getByRole("textbox", { name: "Decision reason" })
    .fill("Need a second calibrated weight observation.");
  await page
    .getByRole("button", { name: "Reject action", exact: true })
    .click();
  await page.getByRole("tab", { name: /Needs evidence/ }).click();
  await expect(page.locator("tbody")).toContainText("SHP-10479");
  await page
    .getByRole("button", { name: "Review SHP-10479", exact: true })
    .click();
  await page.getByRole("button", { name: "Escalate for evidence" }).click();
  await page
    .getByRole("textbox", { name: "Decision reason" })
    .fill("Dispatch supervision must obtain the missing weight proof.");
  await page
    .getByRole("button", { name: "Escalate case", exact: true })
    .click();
  await page.getByRole("tab", { name: /Decision history/ }).click();
  await expect(page.locator("tbody")).toContainText(
    "Need a second calibrated weight observation.",
  );
  await expect(page.locator("tbody")).toContainText(
    "Dispatch supervision must obtain the missing weight proof.",
  );
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]'),
  ).toHaveCount(0);
});

test("Failed mock recovery shows error feedback and remains unresolved", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-10-09T12:00:00+03:00") });
  await page.clock.pauseAt(new Date("2026-10-09T12:00:10+03:00"));
  await page.goto("/cases/SHP-10482");
  await settlePausedWorkspace(page, "SHP-10482");
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await settlePausedWorkspace(page, "Settings");
  await choose(page, "Simulation scenario", "Failed automated intervention");
  await page.clock.runFor(50);
  await page.getByRole("button", { name: "Add case", exact: true }).click();
  await page.clock.runFor(50);
  await page
    .locator('[data-sonner-toast][data-type="info"]')
    .getByRole("button", { name: "Open case", exact: true })
    .click();
  await settlePausedWorkspace(page, "SHP-10499");
  await page
    .getByRole("button", { name: "Investigate now", exact: true })
    .click();
  await page.clock.runFor(50);
  for (let i = 0; i < 5; i++) await page.clock.runFor(2400);
  await expect(page.locator(".case-heading")).toContainText(
    "Awaiting approval",
  );
  await page
    .getByRole("button", { name: "Review & authorize", exact: true })
    .click();
  await page.clock.runFor(50);
  await page
    .getByRole("textbox", { name: "Decision reason" })
    .fill(
      "Authorize the proposed recovery and verify its outcome independently.",
    );
  await page.clock.runFor(50);
  await page
    .getByRole("button", { name: "Authorize action", exact: true })
    .click();
  await page.clock.runFor(50);
  await expect(page.locator(".case-heading")).toContainText("Executing");
  await page.clock.runFor(2400);
  await expect(page.locator(".case-heading")).toContainText("Verifying");
  await page.clock.runFor(2400);
  await expect(page.locator(".case-heading")).toContainText("Escalated");
  await expect(
    page.locator('[data-sonner-toast][data-type="error"]'),
  ).toContainText("outcome verification failed");
  await expect(
    page.locator('[data-sonner-toast][data-type="success"]'),
  ).toHaveCount(0);
});

test("Explore links filters, shipment selection, graph layouts, and schema", async ({
  page,
}) => {
  await page.goto("/explore");
  await expect(page.getByTestId("explore-count")).toHaveText("29");
  await choose(page, "Explore destination", "Khobar");
  await choose(page, "Explore origin", "Riyadh");
  await expect(page.getByTestId("explore-count")).toHaveText("8");
  await page.getByTestId("shipment-result-SHP-10497").click();
  await expect(page.getByTestId("shipment-result-SHP-10497")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(
    page.getByRole("region", { name: "Shipment network map" }),
  ).toContainText("8 matching shipments");
  await page.getByRole("tab", { name: "Graph", exact: true }).click();
  await expect(
    page.getByRole("group", { name: "SHP-10497 · shipment", exact: true }),
  ).toBeVisible();
  await choose(page, "Graph entity filter", "Observation");
  await expect(
    page.getByTestId("knowledge-graph").locator(".react-flow__node"),
  ).toHaveCount(6);
  await page.getByRole("tab", { name: "Schema", exact: true }).click();
  await page.getByRole("button", { name: /Vehicle View connections/ }).click();
  await expect(page.locator(".schema-inspector")).toContainText(
    "Movement proves only vehicle location",
  );
  await page.getByRole("button", { name: "Collapse shipment results" }).click();
  await page.getByRole("button", { name: "Expand shipment results" }).click();
  await expect(page.getByTestId("shipment-result-SHP-10497")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.reload();
  await expect(
    page.getByRole("tab", { name: "Schema", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("explore-count")).toHaveText("8");
});

test("Contextual Explore assistant applies real route filters, supports Undo, and refuses decisions", async ({
  page,
}) => {
  await page.goto("/explore");
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await sendHelper(page, "Show shipments from Riyadh to Khobar");
  await expect(page.getByTestId("explore-count")).toHaveText("8");
  await expect(
    page.getByRole("combobox", { name: "Explore origin", exact: true }),
  ).toContainText("Riyadh");
  await expect(
    page.getByRole("combobox", { name: "Explore destination", exact: true }),
  ).toContainText("Khobar");
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Page updated");
  await page.getByRole("button", { name: "Undo filters", exact: true }).click();
  await expect(page.getByTestId("explore-count")).toHaveText("29");
  await sendHelper(page, "Show SHP-10482 on the graph");
  await expect(
    page.getByRole("tab", { name: "Graph", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(page.getByTestId("shipment-result-SHP-10482")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await sendHelper(page, "approve SHP-10482");
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("decision");
  await expect(page.getByTestId("shipment-result-SHP-10482")).toContainText(
    "Awaiting approval",
  );
  await sendHelper(page, "Show teleporting parcels");
  await expect(
    page.getByRole("region", { name: "Canopus conversation transcript" }),
  ).toContainText("Supported examples:");
  await expect(page.getByTestId("explore-count")).toHaveText("1");
});

test("Audit dates, sorting, pagination, details, and shipment timelines are consistent", async ({
  page,
}) => {
  await page.goto("/audit");
  const today = Number(await page.getByTestId("audit-event-count").innerText());
  expect(today).toBeGreaterThan(20);
  const firstTime = await page
    .locator("tbody tr")
    .first()
    .locator("td")
    .first()
    .innerText();
  await page.getByRole("button", { name: "Next table page" }).click();
  expect(
    await page.locator("tbody tr").first().locator("td").first().innerText(),
  ).not.toBe(firstTime);
  await choose(page, "Audit date range", "This month");
  await expect
    .poll(async () =>
      Number(await page.getByTestId("audit-event-count").innerText()),
    )
    .toBeGreaterThan(today);
  await page.getByRole("button", { name: "Toggle audit time order" }).click();
  await expect(page.locator(".audit-results-meta")).toContainText("Newest");
  await page.getByRole("button", { name: "Choose custom audit dates" }).click();
  const calendar = page.locator('[data-slot="calendar"]');
  await calendar.getByRole("button", { name: /October 2nd, 2026/ }).click();
  await calendar.getByRole("button", { name: /October 2nd, 2026/ }).click();
  await page.getByRole("button", { name: "Apply dates", exact: true }).click();
  await expect(page.locator("tbody tr")).toHaveCount(10);
  await expect(page.locator("tbody tr").first()).toContainText("SHP-10442");
  await page.locator(".audit-event-button").first().click();
  await expect(page.getByRole("dialog")).toContainText("Recorded time");
  await expect(page.getByRole("dialog")).toContainText("Evidence references");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page.goto("/audit?case=SHP-10482&mode=by_shipment&timeRange=all");
  await expect(page.locator(".timeline-header")).toContainText("SHP-10482");
  await expect(page.locator(".timeline-events")).toContainText(
    "Custody contradiction detected",
  );
  await page.reload();
  await expect(page.locator(".timeline-header")).toContainText("SHP-10482");
  await page.getByRole("link", { name: "Open case", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "SHP-10482", exact: true }),
  ).toBeVisible();
});

test("Audit assistant applies date, route, failed-outcome filters and restores the previous view", async ({
  page,
}) => {
  await page.goto("/audit");
  const initial = await page.getByTestId("audit-event-count").innerText();
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await sendHelper(page, "Show this month's failed outcomes");
  await expect(page.getByTestId("audit-event-count")).toHaveText("2");
  await expect(page.locator("tbody")).toContainText(
    "Outcome verification failed",
  );
  await expect(page.locator("tbody")).toContainText("SHP-10486");
  await page.getByRole("button", { name: "Undo filters", exact: true }).click();
  await expect(page.getByTestId("audit-event-count")).toHaveText(initial);
  await sendHelper(page, "Show shipments that arrived in Riyadh this month");
  await page
    .getByRole("button", { name: "Minimize Canopus conversation" })
    .click();
  await page.getByRole("button", { name: "More filters", exact: true }).click();
  await expect(
    page.getByRole("combobox", { name: "Audit destination", exact: true }),
  ).toContainText("Riyadh");
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("combobox", { name: "Audit date range", exact: true }),
  ).toContainText("This month");
  await expect(
    page.getByRole("tab", { name: "By shipment", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await page.getByRole("button", { name: /SHP-10442 Dammam → Riyadh/ }).click();
  await expect(page.locator(".timeline-header")).toContainText("SHP-10442");
  await expect(page.locator(".timeline-events")).toContainText(
    "Case independently verified and resolved",
  );
});

test("Global search, notification drawer, persistent theme, Arabic layout, and mobile navigation", async ({
  page,
}) => {
  await page.goto("/operations");
  await page.keyboard.press("Control+k");
  await page
    .getByRole("textbox", { name: "Global shipment search" })
    .fill("10482");
  await page
    .getByRole("dialog")
    .getByRole("link", { name: /SHP-10482/ })
    .click();
  await expect(
    page.getByRole("heading", { name: "SHP-10482", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Notifications", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    "Recent events from the local simulation.",
  );
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Close", exact: true })
    .click();
  await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.goto("/settings");
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.getByRole("button", { name: "Dark theme", exact: true }).click();
  await page
    .getByRole("button", { name: "Switch to Arabic", exact: true })
    .click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByRole("heading", { name: "الإعدادات", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "التحقيق", exact: true }).click();
  await expect(page.getByTestId("route-map")).toBeVisible();
  await expect(page.getByTestId("knowledge-graph")).toBeVisible();
  const map = (await page.getByTestId("route-map").boundingBox())!,
    graph = (await page.getByTestId("knowledge-graph").boundingBox())!;
  expect(Math.abs(map.y - graph.y)).toBeLessThan(3);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    )
    .toBe(true);
  await page
    .getByRole("button", { name: "تبديل الشريط الجانبي", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByRole("link", { name: "استكشاف", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "استكشاف", exact: true }),
  ).toBeVisible();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    )
    .toBe(true);
});

test("Every page is complete across desktop and mobile, with no application errors", async ({
  page,
}) => {
  test.setTimeout(90000);
  const routes = [
    ["operations", "Operations"],
    ["cases/SHP-10482", "SHP-10482"],
    ["decisions", "Decisions"],
    ["explore", "Explore"],
    ["audit", "Audit"],
    ["settings", "Settings"],
  ];
  for (const [route, title] of routes) {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/${route}`);
    await expect(
      page.getByRole("heading", { name: title, exact: true, level: 1 }),
    ).toBeVisible();
    await expect(page.locator("main")).not.toContainText("Unable to load");
    const nodes = page.locator(".react-flow__node");
    if (route.startsWith("cases")) {
      await expect(nodes.first()).toBeVisible();
      await waitForGraphFit(page);
    }
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    await page.screenshot({
      path: `screenshots/final-${route.split("/")[0]}-desktop.png`,
      fullPage: true,
      animations: "disabled",
    });
    await page.setViewportSize({ width: 390, height: 844 });
    if (route.startsWith("cases")) await waitForGraphFit(page);
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    await page.screenshot({
      path: `screenshots/final-${route.split("/")[0]}-mobile.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.getByRole("button", { name: "Toggle theme", exact: true }).click();
  for (const [route, title] of routes
    .slice(0, 5)
    .filter(([route]) => route !== "decisions")) {
    await page.goto(`/${route}`);
    await expect(
      page.getByRole("heading", { name: title, exact: true, level: 1 }),
    ).toBeVisible();
    await expect(page.locator("html")).toHaveClass(/dark/);
    if (route.startsWith("cases")) await waitForGraphFit(page);
    await expect
      .poll(() =>
        page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth + 1,
        ),
      )
      .toBe(true);
    await page.screenshot({
      path: `screenshots/final-${route.split("/")[0]}-dark.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/cases/SHP-10482");
  await waitForGraphFit(page);
  const map = (await page.getByTestId("route-map").boundingBox())!,
    graph = (await page.getByTestId("knowledge-graph").boundingBox())!;
  expect(Math.abs(map.y - graph.y)).toBeLessThan(3);
  expect(graph.x).toBeGreaterThan(map.x);
  await page.screenshot({
    path: "screenshots/final-investigation-laptop-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.goto("/cases/SHP-99999");
  await expect(
    page.getByText("Shipment not found", { exact: true }),
  ).toBeVisible();
});
