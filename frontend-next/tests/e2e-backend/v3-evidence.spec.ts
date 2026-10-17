import { test, expect } from "@playwright/test";
import { stubBackend } from "./backend-stub";
import { CASE_V3, detailV3Route } from "../fixtures/backend";

test("Evidence chronology stays visible when the backend sends a case brief", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.detailV3 = detailV3Route({
    brief: {
      resolved: false,
      waiting_kind: "human_investigation",
      waiting_label_en: "Human investigation",
      lines: [
        {
          key: "problem",
          label_en: "Problem",
          text_en:
            "Delivery authentication failed while vehicle telemetry continued.",
        },
        {
          key: "finding",
          label_en: "Finding",
          text_en:
            "Authentication evidence did not validate the recorded handoff.",
        },
        {
          key: "action",
          label_en: "Action taken",
          text_en: "Case kept open for operator review.",
        },
        {
          key: "status",
          label_en: "Current status",
          text_en: "Awaiting human investigation.",
        },
      ],
      suspected_cause: {
        status: "accepted",
        text_en: "Failed delivery authentication.",
        confidence: "medium",
      },
      evidence: [
        {
          id: "SYN-SHP-000051-CUST-008",
          label_en: "Final custody observation",
          in_graph: true,
        },
      ],
      review: null,
      policy: {
        decision: "manual",
        text_en: "Requires human review.",
        rule_id: "AUTH-21-human-investigation-required",
      },
      actions: [],
      technical: {
        workflow_state: "HUMAN_REVIEW",
        authority_rule_id: "AUTH-21-human-investigation-required",
      },
    },
    pipeline: {
      events: [],
      status: "REVIEWED",
      stage_facts: [
        {
          stage: "classify",
          status: "done",
          fact_en: "Failed authentication on delivery evidence.",
          sequence: 3,
        },
      ],
    },
  });
  await page.goto(`/app/cases/${CASE_V3}`);
  await expect(page.getByTestId("case-assessment")).toContainText(
    "Delivery authentication failed while vehicle telemetry continued.",
  );
  await expect(page.getByTestId("evidence-chronology")).toBeVisible();
  await expect(page.getByTestId("route-evidence-range")).toContainText(
    "Vehicle observations",
  );
  await expect(
    page.getByTestId("chronology-SYN-GPS-FM-JED-003-20260914T110413"),
  ).toBeVisible();
});

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
