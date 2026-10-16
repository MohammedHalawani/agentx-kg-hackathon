import { test, expect } from "@playwright/test";
import { stubBackend } from "./backend-stub";
import { CASE_A } from "../fixtures/backend";

// V3.4: four workers in the left sidebar, from worker.active_cases and provider.calls as the backend reports them.
// Scripted backend stand-in: this checks the layout and the wiring, not live inference.
const captures = "../artifacts/v34-four-lane/screenshots";

for (const state of ["expanded", "collapsed"] as const) {
  test(`four workers fit the sidebar ${state} and show only reported activity`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const stub = await stubBackend(page);
    stub.state.quadWorker = true;
    stub.state.worker = "running";
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`/app/cases/${CASE_A}`);
    const agents = page.getByTestId("working-agents");
    await expect(agents).toBeVisible();
    await expect(agents.getByRole("link")).toHaveCount(4);
    // The investigation screen may open with the sidebar collapsed; put it in the state under test.
    const collapsed = page.locator('[data-slot="sidebar"][data-state="collapsed"], .group[data-state="collapsed"]');
    await page.waitForTimeout(300);
    if ((await collapsed.count()) > 0 !== (state === "collapsed"))
      await page.getByRole("button", { name: "Toggle Sidebar" }).click();
    if (state === "collapsed") await expect(collapsed.first()).toBeAttached();
    else await expect(collapsed).toHaveCount(0);
    if (state === "expanded") {
      await expect(agents).toContainText("4 / 4");
      const lanes = page.getByTestId("provider-lanes");
      await expect(lanes).toBeVisible();
      await expect(lanes).toContainText("3/4");             // lane C cools down: three in service
      await expect(lanes.locator('[data-lane="C"]')).toHaveAttribute("data-state", "cooling");
      await expect(page.getByTestId("worker-capacity")).toContainText("0");
    }
    // Activity follows the backend's call report: two in a call, one waiting for a lane, one in neither.
    const tile = (caseId: string) => page.getByTestId(`worker-case-${caseId}`);
    await expect(tile(CASE_A)).toHaveAttribute("data-model-call", "A");
    await expect(tile(CASE_A)).toHaveAttribute("data-running", "true");
    await expect(tile("SYN-OPS-CASE-QUAD-3")).toHaveAttribute("data-model-call", "waiting");
    await expect(tile("SYN-OPS-CASE-QUAD-3")).toHaveAttribute("data-running", "false");
    await expect(tile("SYN-OPS-CASE-QUAD-4")).toHaveAttribute("data-model-call", "none");
    await expect(tile("SYN-OPS-CASE-QUAD-4")).toHaveAttribute("data-running", "false");
    if (state === "expanded")
      await expect(tile("SYN-OPS-CASE-QUAD-3")).toContainText("waiting for a lane");
    // Every tile stays inside the sidebar, nothing overlaps, and the page does not scroll sideways.
    const sidebar = (await page.locator('[data-sidebar="sidebar"]').first().boundingBox())!;
    const boxes = [];
    for (const element of await agents.locator(".worker-tile").all()) boxes.push((await element.boundingBox())!);
    expect(boxes).toHaveLength(5);                            // four assignments and the capacity tile
    for (const box of boxes) {
      expect(box.x).toBeGreaterThanOrEqual(sidebar.x - 0.5);
      expect(box.x + box.width).toBeLessThanOrEqual(sidebar.x + sidebar.width + 0.5);
    }
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i], b = boxes[j];
        const overlap = a.x < b.x + b.width - 0.5 && b.x < a.x + a.width - 0.5 && a.y < b.y + b.height - 0.5 && b.y < a.y + a.height - 0.5;
        expect(overlap, `tiles ${i} and ${j} overlap`).toBe(false);
      }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // The investigation screen stays on the one selected case, whatever the other workers do; nothing was sent.
    await expect(page).toHaveURL(new RegExp(`/cases/${CASE_A}$`));
    await expect(tile(CASE_A)).toHaveAttribute("aria-current", "page");
    expect(stub.posts).toEqual([]);
    expect(errors).toEqual([]);
    await page.screenshot({ path: `${captures}/four-workers-${state}.png` });
  });
}

test("Operations shows four active investigations without the old horizontal worker bar", async ({ page }) => {
  const stub = await stubBackend(page);
  stub.state.quadWorker = true;
  stub.state.worker = "running";
  await page.goto("/app/operations");
  await expect(page.getByTestId("working-agents").getByRole("link")).toHaveCount(4);
  await expect(page.getByTestId("investigation-selector")).toHaveCount(0);   // the V3.2 horizontal selector, removed in 12ef6af
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByTestId("investigation-selector")).toHaveCount(0);
  await page.screenshot({ path: `${captures}/four-workers-operations.png` });
});
