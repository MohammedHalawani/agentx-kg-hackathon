import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * The model-backed path, checked through the interface against a real backend:
 * accepted agent diagnosis -> authority -> approval or automatic execution -> independent
 * verification -> resolution. These tests never start an investigation themselves, so they
 * make no model calls: they need a backend whose ledger already holds agent-investigated
 * cases, and each one skips when the backend has no case in the state it checks.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8010 npm run test:e2e:live
 *
 * The approval test changes a case, so it also needs SUHAIL_LIVE_WRITE=1 (scratch database only).
 */
type Row = {
  case_id: string;
  shipment_id: string;
  workflow_state: string;
  diagnosis_available?: boolean;
};
type Detail = {
  workflow_state: string;
  state_version: number;
  diagnosis: {
    available: boolean;
    summary: string | null;
    primary_cause: string | null;
    tool_calls: number;
    hypotheses: { cause: string; status: string }[];
    review?: { accepted: boolean } | null;
  };
  recommendation: {
    action_en?: string;
    action?: string;
    approvable?: boolean;
    approval_reason?: string;
    risk_class?: string;
  } | null;
  executions: { receipt_ref?: string; current_cycle?: boolean }[];
  outcome: {
    verification_status?: string;
    success?: boolean | null;
    exception_cleared?: boolean | null;
    current_cycle?: boolean;
    invalidated?: boolean;
  } | null;
};
async function cases(request: APIRequestContext) {
  const queue = await request.get("/cases/queue?scope=all&limit=100");
  test.skip(!queue.ok(), "the backend's operations are unavailable");
  const rows = (await queue.json()).items as Row[];
  const details = new Map<string, Detail>();
  for (const row of rows.filter((item) => item.diagnosis_available || item.workflow_state === "RESOLVED" || item.workflow_state === "AWAITING_OUTCOME"))
    details.set(row.case_id, await (await request.get(`/cases/${row.case_id}`)).json());
  return { rows, details };
}

test("An accepted agent diagnosis is shown with its hypotheses, and only then", async ({
  page,
  request,
}) => {
  const { rows, details } = await cases(request);
  const row = rows.find((item) => details.get(item.case_id)?.diagnosis.available);
  test.skip(!row, "no case with an accepted agent diagnosis on this backend");
  const detail = details.get(row!.case_id)!;
  expect(detail.diagnosis.review?.accepted).toBe(true);
  await page.goto(`/app/cases/${row!.case_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(row!.shipment_id);
  // The case is described by the investigator's own accepted summary.
  await expect(page.locator(".case-context")).toContainText(
    detail.diagnosis.summary!.slice(0, 60),
  );
  await page.getByRole("button", { name: "Case details" }).click();
  const findings = page.getByRole("dialog").getByTestId("investigator-findings");
  await expect(findings).toContainText("Investigator's findings");
  await expect(findings).not.toContainText("not accepted by the reviewer");
  await expect(findings.locator(".finding-status")).toHaveCount(
    detail.diagnosis.hypotheses.length,
  );
  await expect(findings).toContainText(`${detail.diagnosis.tool_calls} evidence queries`);
  await expect(page.getByRole("dialog")).toContainText("Independent review");
});

test("An approvable recommendation is offered, approved through the interface, and is not yet a resolution", async ({
  page,
  request,
}) => {
  test.skip(process.env.SUHAIL_LIVE_WRITE !== "1", "set SUHAIL_LIVE_WRITE=1 (scratch database only)");
  const status = await (await request.get("/worker/status")).json();
  expect(String(status.database)).toMatch(/-(ui|test2?|ci-test)$/);
  const { rows, details } = await cases(request);
  const row = rows.find((item) => details.get(item.case_id)?.recommendation?.approvable);
  test.skip(!row, "no case with an approvable recommendation on this backend");
  await page.goto(`/app/cases/${row!.case_id}`);
  await page.getByRole("button", { name: "Review & authorize" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Authorize action" }).click();
  await expect
    .poll(async () => {
      const after = (await (await request.get(`/cases/${row!.case_id}`)).json()) as Detail;
      return after.executions.length;
    })
    .toBeGreaterThan(0);
  const after = (await (await request.get(`/cases/${row!.case_id}`)).json()) as Detail;
  // Whatever the backend did next, the page shows that state and nothing further.
  if (after.workflow_state !== "RESOLVED")
    await expect(page.locator(".case-heading")).not.toContainText("Resolved");
  await page.getByRole("button", { name: "Case details" }).click();
  await expect(page.getByRole("dialog")).toContainText("A receipt is not an outcome");
});

test("An executed action awaiting its outcome is shown as unverified", async ({
  page,
  request,
}) => {
  const { rows, details } = await cases(request);
  const row = rows.find((item) => item.workflow_state === "AWAITING_OUTCOME");
  test.skip(!row, "no case is awaiting its outcome on this backend");
  const detail = details.get(row!.case_id)!;
  await page.goto(`/app/cases/${row!.case_id}`);
  await expect(page.locator(".case-heading")).toContainText("Verifying outcome");
  await expect(page.getByRole("button", { name: "Ask the verifier to check now" })).toBeVisible();
  expect(detail.executions.some((item) => item.current_cycle !== false)).toBe(true);
  await page.getByRole("button", { name: /^Outcome ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(
    "No independently verified outcome is recorded.",
  );
});

test("Only independently verified resolutions appear in Resolved", async ({
  page,
  request,
}) => {
  const { rows, details } = await cases(request);
  const resolved = rows.filter((item) => item.workflow_state === "RESOLVED");
  const verified = resolved.filter((item) => {
    const outcome = details.get(item.case_id)?.outcome;
    return (
      !!outcome &&
      ["VERIFIED", "HUMAN_VERIFIED"].includes(outcome.verification_status ?? "") &&
      outcome.success === true &&
      outcome.exception_cleared !== false &&
      outcome.current_cycle !== false &&
      outcome.invalidated !== true
    );
  });
  await page.goto("/app/operations");
  // A backend that has just started can take several seconds over its first queue read.
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data", {
    timeout: 30000,
  });
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  const rail = page.getByLabel("Verified resolutions");
  // Exactly the backend's verified resolutions (the rail loads the most recent thirty).
  await expect(rail.locator(".resolved-entry")).toHaveCount(Math.min(verified.length, 30));
  for (const row of verified.slice(-3))
    await expect(rail).toContainText(row.shipment_id);
  if (verified.length) {
    await page.goto(`/app/cases/${verified.at(-1)!.case_id}`);
    await expect(page.locator(".case-heading")).toContainText("Resolved");
    await page.getByRole("button", { name: /^Outcome ·/ }).click();
    await expect(page.locator(".pipeline-stage-summary")).not.toContainText(
      "No independently verified outcome",
    );
  }
});
