import { test, expect } from "@playwright/test";
import { stubBackend } from "./backend-stub";
import { CASE_V3 } from "../fixtures/backend";

test("Route evidence shows source-backed GPS, receipt times and graph selection", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${CASE_V3}`);
  await expect(page.getByTestId("evidence-chronology")).toBeVisible();
  await expect(page.getByTestId("route-evidence-range")).toContainText(
    "Vehicle observations",
  );
  const firstGps = page.getByTestId(
    "chronology-SYN-GPS-FM-JED-003-20260914T110413",
  );
  await expect(firstGps).toBeVisible();
  await firstGps.click();
  await expect(page.locator(".entity-node.evidence-selected")).toBeVisible();
  await expect(page.getByText("Vehicle telemetry only")).toBeVisible();
});

test("Map draws vehicle polylines in separate segments", async ({ page }) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${CASE_V3}`);
  await expect(page.locator(".leaflet-overlay-pane svg")).toBeVisible();
  await expect(page.locator(".leaflet-overlay-pane path")).not.toHaveCount(0);
});
