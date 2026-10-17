import { expect, test } from "@playwright/test";
import { stubBackend } from "./backend-stub";
import { CASE_A, SHIP_A, detailA } from "../fixtures/backend";
import type { ApiBrief } from "../../src/api/contracts";

/** A brief in the backend's shape (chat/operations/brief.py) for a case waiting for a person. */
const brief: ApiBrief = {
  resolved: false,
  waiting_kind: "awaiting_operator_decision",
  waiting_label_en: "Waiting for a person",
  lines: [
    {
      key: "problem",
      label_en: "Problem",
      text_en: "The delivery session ended with this parcel unaccounted for.",
    },
    {
      key: "finding",
      label_en: "Finding",
      text_en:
        "Suhail's investigation concluded that the cause is custody that was not reconciled.",
    },
    {
      key: "action",
      label_en: "Action taken",
      text_en: "Recommended: custody reconciliation request.",
    },
    {
      key: "status",
      label_en: "Current status",
      text_en: "Approve or reject the custody reconciliation request.",
    },
  ],
  what_happened: {
    text_en: "Suhail's monitor opened this case for shipment SYN-SHP-000101.",
  },
  suspected_cause: {
    status: "accepted",
    label_en: "custody that was not reconciled",
    text_en:
      "Suhail's investigation concluded that the cause is custody that was not reconciled, and the independent review accepted it.",
    confidence: "medium",
  },
  evidence: [
    {
      id: `${SHIP_A}-CUST-02-01`,
      kind: "CustodyEvent",
      label_en: "Depot custody scan",
      in_graph: true,
    },
  ],
  review: {
    status: "accepted",
    text_en: "The independent review accepted this conclusion.",
  },
  policy: {
    decision: "needs_approval",
    text_en: "This action needs an operator's approval.",
    rule_id: "AUTH-11-approval-required",
  },
  actions: [],
  verification: {
    status: "not_applicable",
    text_en: "No request has been sent, so there is nothing to verify.",
  },
  technical: {
    workflow_state: "AWAITING_APPROVAL",
    authority_rule_id: "AUTH-11-approval-required",
    review_verdict: "ACCEPT",
    run_id: "SYN-RUN-1",
  },
};

test("A reviewed case opens in Decision view and the full Evidence view is one click away", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.detailA = detailA({ brief });
  await page.goto(`/app/cases/${CASE_A}`);
  const order = page.getByTestId("work-order");
  await expect(order).toBeVisible();
  // The four leading facts, in the backend's own words.
  await expect(page.getByTestId("order-happened")).toContainText(
    "The delivery session ended with this parcel unaccounted for.",
  );
  await expect(page.getByTestId("order-next")).toBeVisible();
  await expect(page.getByTestId("order-party")).toContainText(
    "A driver assignment is not custody",
  );
  await expect(page.getByTestId("order-status-row")).toContainText(
    "Approve or reject the custody reconciliation request.",
  );
  // Consolidated: the sidebar assessment and the separate next-step strip are not repeated.
  await expect(page.getByTestId("case-assessment")).toBeHidden();
  await expect(page.getByTestId("next-step")).toHaveCount(0);
  // The live map is still on the page in Decision view.
  await expect(
    page.locator(".evidence-split .leaflet-container"),
  ).toBeVisible();
  // Secondary detail folds out; evidence ids are genuine and clickable.
  await order.getByRole("button", { name: /Supporting evidence/ }).click();
  await expect(order).toContainText(`${SHIP_A}-CUST-02-01`);
  await page.screenshot({
    path: "test-results/ui-final/decision-view.png",
    fullPage: true,
  });
  // One click back to the original workspace, with the graph and sidebar.
  await order.getByRole("button", { name: "View knowledge graph" }).click();
  await expect(page.getByTestId("work-order")).toHaveCount(0);
  await expect(page.getByTestId("case-assessment")).toBeVisible();
  await expect(page.locator(".graph-layer")).toBeVisible();
  await expect(page.locator(".graph-layer")).not.toHaveAttribute(
    "aria-hidden",
    "true",
  );
  await page.screenshot({
    path: "test-results/ui-final/evidence-view.png",
    fullPage: true,
  });
  // And back, from the switch.
  await page
    .getByTestId("view-switch")
    .getByRole("button", { name: "Decision view" })
    .click();
  await expect(page.getByTestId("work-order")).toBeVisible();
  // Nothing was posted by switching views.
  expect(stub.posts).toEqual([]);
});

test("A case without a brief, or still investigating, never shows a work order", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByTestId("evidence-inspector")).toBeVisible();
  await expect(page.getByTestId("work-order")).toHaveCount(0);
  await expect(page.getByTestId("view-switch")).toHaveCount(0);
});

test("Operations shows five columns with the recorded priority, KPI cards and the decisions link", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto("/app/operations");
  const headers = page.locator(".operations-ledger thead th");
  await expect(headers).toHaveText([
    "Priority↕",
    "Shipment",
    "Problem",
    "Next action",
    "Last update · AST",
    "",
  ]);
  await expect(page.locator(".operations-ledger")).not.toContainText(
    "Workflow",
  );
  // An uninvestigated case shows a pending state, not an invented action.
  await expect(page.locator(".next-action-cell").first()).toHaveText(
    "Awaiting investigation",
  );
  await expect(
    page.locator(".domain-data-table .priority").first(),
  ).toBeVisible();
  // KPI cards carry the backend's counts.
  await expect(page.getByTestId("kpi-open")).toHaveText("2");
  await expect(page.getByTestId("kpi-awaiting")).toHaveText("1");
  await expect(page.getByTestId("kpi-verified")).toHaveText("1");
  await expect(page.getByTestId("monitoring-status")).toContainText(
    "32 of 40 booked shipments checked",
  );
  await page.screenshot({
    path: "test-results/ui-final/operations-kpis.png",
    fullPage: true,
  });
  // A KPI applies a visible filter, cleared from the page.
  await page.getByRole("button", { name: /Action pending/ }).click();
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toBeVisible();
  await page.getByRole("button", { name: "Clear applied filters" }).click();
  // Waiting / Closed panel with its link to Decisions.
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(page.getByTestId("view-all-decisions")).toBeVisible();
  await page.screenshot({
    path: "test-results/ui-final/operations-panel.png",
    fullPage: true,
  });
  await page.getByTestId("view-all-decisions").click();
  await expect(page).toHaveURL(/\/app\/decisions$/);
  await expect(page.getByTestId("decision-kpis")).toBeVisible();
  await page.screenshot({
    path: "test-results/ui-final/decisions-kpis.png",
    fullPage: true,
  });
});

test("Canopus on Operations applies a visible, reversible view without a model call", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await page
    .getByRole("button", {
      name: "Which cases need immediate human attention?",
    })
    .click();
  await expect(page.getByTestId("operations-answer")).toContainText(
    "no AI model used",
  );
  const chip = page.getByTestId("assistant-view");
  await expect(chip).toContainText("Need a person now");
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toBeVisible();
  const ask = page.getByRole("textbox", {
    name: "Ask Canopus about the queue",
  });
  await ask.fill("Filter to barcode problems");
  await ask.press("Enter");
  await expect(chip).toContainText("barcode");
  await page
    .getByRole("button", { name: "Minimize Canopus conversation" })
    .click();
  await chip.getByRole("button", { name: "Undo" }).click();
  await expect(chip).toContainText("Need a person now");
  await chip.getByRole("button", { name: "Clear Canopus view" }).click();
  await expect(page.getByTestId("assistant-view")).toHaveCount(0);
  // The assistant only reads: no request reached the backend.
  expect(stub.posts).toEqual([]);
});

test("A case question goes to that case only and is labelled by who wrote it", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.detailA = detailA({ brief });
  await page.goto(`/app/cases/${CASE_A}`);
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await page
    .getByRole("button", { name: "What happened to this shipment?" })
    .click();
  const answer = page.getByTestId("canopus-answer");
  await expect(answer).toContainText(
    "written by gpt-oss:120b from this case's records",
  );
  await expect(page.getByTestId("canopus-on-record")).toContainText(
    "accepted by the independent review",
  );
  expect(stub.posts.map((post) => post.path)).toEqual([
    `/cases/${CASE_A}/canopus/ask`,
  ]);
  // Another case's panel does not carry this conversation.
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await expect(page.getByTestId("canopus-ask-thread")).toHaveCount(0);
});

test("Sidebar: no guide entry or duplicate connection line, expanded and collapsed", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto("/app/operations");
  const sidebar = page.locator("[data-sidebar=sidebar]").first();
  await expect(sidebar).not.toContainText("Workspace guide");
  await expect(sidebar).not.toContainText("Backend connected");
  await expect(
    page.getByRole("button", { name: "Workspace guide" }),
  ).toBeVisible();
  await page.screenshot({ path: "test-results/ui-final/sidebar-expanded.png" });
  await page.getByRole("button", { name: "Toggle sidebar" }).click();
  await page.waitForTimeout(400);
  await page.screenshot({
    path: "test-results/ui-final/sidebar-collapsed.png",
  });
});
