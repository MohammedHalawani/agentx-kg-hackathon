import { expect, test } from "@playwright/test";

/**
 * The demo's completed lifecycle, read through the interface from the demo backend. Read-only:
 * it opens pages and reads the API; it sends no operator request.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8020 SUHAIL_DEMO_CASE=<case id> npx playwright test \
 *     --config playwright.live.config.ts demo-first-case
 */
const CASE = process.env.SUHAIL_DEMO_CASE;
test.skip(!CASE, "set SUHAIL_DEMO_CASE to a case that completed the lifecycle");
const shot = (name: string) => `screenshots/demo-${name}.png`;

test("Every stage of a completed lifecycle is displayed as the backend recorded it", async ({
  page,
  request,
}) => {
  const detail = await (await request.get(`/cases/${CASE}`)).json();
  const log = detail.run.result.investigation_log;
  const execution = detail.executions[0];
  const outcome = detail.outcome;
  await page.goto(`/app/cases/${CASE}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(detail.shipment_id, {
    timeout: 30000,
  });
  // Detection and diagnosis: the accepted diagnosis describes the case.
  expect(detail.diagnosis.available).toBe(true);
  await expect(page.locator(".case-context")).toContainText(
    detail.diagnosis.summary.slice(0, 50),
  );
  // Evidence: the backend's custody points on the map, real nodes in the graph.
  await expect(
    page.getByTestId("route-map").locator(".evidence-marker.confirmed"),
  ).toHaveCount(detail.route_layers.layers.custody_points.length);
  await expect(
    page.getByTestId("knowledge-graph").locator(".entity-node").first(),
  ).toBeVisible();
  // Recommendation and its authority level.
  await expect(page.locator(".case-context")).toContainText(detail.recommendation.action_en);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: shot("case"), fullPage: true });

  // The rail: each recorded stage, and the outcome stage as the verifier left it.
  for (const stage of ["Collect", "Graph", "Diagnose", "Precedent", "Recommend", "Review", "Route"])
    await expect(
      page.getByRole("button", { name: new RegExp(`^${stage} · completed`) }),
    ).toBeVisible();
  if (!outcome) {
    // Executed, answer not in yet: shown as waiting for the verifier, never as an outcome.
    expect(detail.workflow_state).toBe("AWAITING_OUTCOME");
    await expect(page.locator(".case-heading")).toContainText("Verifying outcome");
    await expect(
      page.getByRole("button", { name: "Ask the verifier to check now" }),
    ).toBeVisible();
    await page.getByRole("button", { name: /^Outcome ·/ }).click();
    await expect(page.locator(".pipeline-stage-summary")).toContainText(
      "No independently verified outcome is recorded.",
    );
    await page.screenshot({ path: shot(`awaiting-${detail.shipment_id}`), fullPage: true });
    await page.getByRole("button", { name: "Case details" }).click();
    const waiting = page.getByRole("dialog");
    await expect(waiting).toContainText("A receipt is not an outcome");
    await expect(waiting).toContainText("Waiting for evidence of the outcome");
    await waiting.getByText("Waiting for evidence of the outcome").scrollIntoViewIfNeeded();
    await page.screenshot({ path: shot(`awaiting-assessment-${detail.shipment_id}`) });
    return;
  }
  const cleared = outcome.success === true && outcome.exception_cleared !== false;
  await expect(
    page.getByRole("button", {
      name: new RegExp(`^Outcome · ${cleared ? "completed" : "failed"}`),
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: /^Outcome ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(outcome.reason);
  await page.getByRole("button", { name: /^Review ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText("Reviewer verdict");
  await page.screenshot({ path: shot("rail") });

  // The assessment: investigation steps, review, authority, execution, verification.
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  const calls = (log.rounds as { tool_calls: unknown[] }[]).reduce(
    (sum, round) => sum + round.tool_calls.length,
    0,
  );
  const steps = sheet.getByTestId("investigation-steps");
  await expect(steps.locator(".investigation-steps li")).toHaveCount(calls);
  await expect(steps).toContainText(
    `${log.model_calls_used} of ${log.model_call_cap} model calls`,
  );
  await page.screenshot({ path: shot("assessment-investigation") });
  await expect(sheet.getByTestId("investigator-findings").locator(".finding-status")).toHaveCount(
    detail.diagnosis.hypotheses.length,
  );
  await expect(sheet.getByTestId("review-rounds")).toContainText("Independent model review");
  await expect(sheet.getByTestId("authority-decision")).toContainText(
    detail.run.result.authority.rule_id,
  );
  const verification = sheet.getByTestId("verification-result");
  await verification.scrollIntoViewIfNeeded();
  await expect(verification).toContainText(outcome.reason);
  await expect(verification).toContainText(
    cleared
      ? "Answered · verified · exception cleared"
      : outcome.success
        ? "Verified · exception remains"
        : outcome.outcome_type === "no_confirming_evidence"
          ? "Delivered · no answer by the deadline"
          : "Answered · not confirmed",
  );
  await expect(sheet).toContainText("A receipt is not an outcome");
  expect(execution.status).toBe("ACKNOWLEDGED");
  await page.screenshot({ path: shot("assessment-verification") });
  await page.keyboard.press("Escape");

  // The case is where the backend says it is, and is in Resolved only if it resolved.
  await expect(page.locator(".case-heading")).toContainText(
    detail.workflow_state === "RESOLVED" ? "Resolved" : "Human investigation",
  );
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data", {
    timeout: 30000,
  });
  await page.getByRole("textbox", { name: "Search exception queue" }).fill(detail.shipment_id);
  await page.waitForTimeout(500);
  await page.screenshot({ path: shot("operations") });
  await page.goto(`/app/audit?case=${CASE}&mode=by_shipment&timeRange=all`);
  await expect(page.locator(".timeline-events")).toContainText("Outcome", {
    timeout: 60000,
  });
  await page.screenshot({ path: shot("audit") });
});
