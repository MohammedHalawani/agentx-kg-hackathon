import { expect, test } from "@playwright/test";

/**
 * Every demo story case, read through the interface from the demo backend and checked
 * against that backend's own API. Read-only: pages are opened and the API is read.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8020 SUHAIL_DEMO_CASES=<id>,<id>,... npx playwright test \
 *     --config playwright.live.config.ts demo-stories
 */
const CASES = (process.env.SUHAIL_DEMO_CASES ?? "").split(",").filter(Boolean);
test.skip(CASES.length === 0, "set SUHAIL_DEMO_CASES to the story case ids");
test.setTimeout(120000);

const LABEL: Record<string, string> = {
  OPEN: "Queued",
  INVESTIGATING: "Investigating",
  AWAITING_APPROVAL: "Awaiting approval",
  HUMAN_REVIEW: "Human investigation",
  AWAITING_OUTCOME: "Verifying outcome",
  ESCALATED: "Escalated",
  REJECTED: "Action rejected",
  NEEDS_EVIDENCE: "Needs evidence",
  RESOLVED: "Resolved",
};

for (const id of CASES)
  test(`Story case ${id.slice(-8)} renders as the backend recorded it`, async ({
    page,
    request,
  }) => {
    const detail = await (await request.get(`/cases/${id}`)).json();
    const result = detail.run?.result ?? {};
    const degraded: { kind: string }[] = result.degraded ?? [];
    const execution = (detail.executions ?? [])[0];
    const outcome = detail.outcome;
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`/app/cases/${id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(detail.shipment_id, {
      timeout: 60000,
    });
    // It is a case page, never an error page.
    await expect(page.locator(".app-error")).toHaveCount(0);
    await expect(page.locator(".case-heading")).toContainText(LABEL[detail.workflow_state]);

    // Why the case is unresolved and what it needs next, exactly as the backend states it.
    const next = detail.next_step;
    if (next) {
      // The pipeline card ends with the next best action, in the backend's own words.
      const panel = page.locator(".pipeline").getByTestId("next-step");
      await expect(panel).toContainText("NEXT BEST ACTION", { timeout: 45000 });
      await expect(panel).toContainText(next.text_en);
      if (!next.resolved && next.blocked_by?.rule_id) {
        await panel.getByRole("button", { name: "Why, and what is missing" }).click();
        await expect(panel).toContainText(next.blocked_by.rule_id);
        for (const item of next.missing_evidence ?? []) await expect(panel).toContainText(item);
      }
    } else await expect(page.getByTestId("next-step")).toHaveCount(0);
    // A case the workflow routed or escalated to a person is not shown as a failed step.
    if (["ESCALATED", "HUMAN_REVIEW"].includes(detail.workflow_state) && !degraded.length && !(execution?.status === "NOT_ACKNOWLEDGED"))
      await expect(page.locator(".pipeline-step.state-failed")).toHaveCount(0);
    if (detail.workflow_state === "ESCALATED")
      await expect(page.getByRole("button", { name: /^Disposition · waiting/ })).toContainText(
        "Escalated to a person",
      );
    // The graph opens focused: fewer nodes than the records it draws from, all of them real.
    await expect(
      page.getByTestId("knowledge-graph").locator(".entity-node").first(),
    ).toBeVisible({ timeout: 30000 });
    const drawn = await page.getByTestId("knowledge-graph").locator(".entity-node").count();
    expect(drawn).toBeGreaterThan(3);
    expect(drawn).toBeLessThanOrEqual(48);
    // Stored narration, where the run has one: every message labelled by its source, none
    // composed here; a run without narration shows no strip.
    const narration: { kind: string; stage: string }[] = detail.narration?.events ?? [];
    if (narration.length) {
      const strip = page.getByTestId("narration-strip");
      await expect(strip).toContainText(`of ${narration.length} recorded messages`);
      await page.getByRole("button", { name: /^Review ·/ }).click();
      const kinds = new Set(
        narration.filter((event) => event.stage === "review").map((event) => event.kind),
      );
      for (const kind of kinds)
        await expect(
          strip.locator(`[data-testid="narration-bubble"][data-kind="${kind}"]`).first(),
        ).toBeVisible();
      await page.getByRole("button", { name: "Follow current stage" }).click();
    } else await expect(page.getByTestId("narration-strip")).toHaveCount(0);
    const context = page.locator(".case-context");
    // An accepted finding is the agent's, unverified; without one, only what the monitor saw.
    await expect(page.getByTestId("context-source")).toContainText(
      detail.diagnosis.available ? /agent's finding.*not verified/i : /monitor observed/i,
    );
    // Routing to a person is the policy's, named by its rule.
    const rule = result.authority?.rule_id;
    if (
      detail.workflow_state === "HUMAN_REVIEW" &&
      rule &&
      !(result.degraded ?? []).length &&
      !execution &&
      !outcome
    )
      await expect(page.locator(".pipeline-meta")).toContainText(
        `Routed to a person by policy rule ${rule}`,
      );
    if (detail.diagnosis.available)
      await expect(context).toContainText(detail.diagnosis.summary.slice(0, 40));
    else
      // No accepted diagnosis: the monitor's neutral sentence, never a cause.
      await expect(context).toContainText(/no accepted agent diagnosis|Monitor detected/i);
    // Evidence that moved during the run is not a model failure and leaves the diagnosis shown.
    const snapshot = (result.degraded ?? []).some(
      (item: { role?: string; kind?: string }) =>
        item.role === "snapshot" || item.kind === "snapshot_superseded",
    );
    if (snapshot)
      await expect(page.locator(".pipeline-meta")).toContainText(
        "Evidence changed during the investigation",
      );
    else if (degraded.length)
      await expect(page.locator(".pipeline-meta")).toContainText(
        degraded.some((item) => item.kind === "turn_budget_exhausted")
          ? "reached no conclusion within its turn budget"
          : degraded.some((item) => item.kind === "model_unavailable")
            ? "The model was unavailable"
          : "The model's reply could not be used",
      );
    if (execution?.status === "NOT_ACKNOWLEDGED" && !degraded.length)
      await expect(page.locator(".pipeline-meta")).toContainText(
        "The request could not be delivered",
      );
    // Delivered and waiting: when an answer is due, never what the answer will be.
    if (detail.workflow_state === "AWAITING_OUTCOME" && execution?.deadline_at)
      await expect(page.locator(".pipeline-meta")).toContainText(
        execution.expected_response_at ? "an answer is scheduled for" : "answer expected by",
      );
    // An action that worked while the exception remains is not shown as a failed check.
    if (outcome?.success === true && outcome.exception_cleared === false) {
      await expect(page.locator(".pipeline-meta")).toContainText("the exception remains");
      await expect(page.getByRole("button", { name: /^Outcome · waiting/ })).toBeVisible();
    }
    await page.waitForTimeout(1500);
    const name = `${detail.shipment_id.slice(-3)}-${String(detail.workflow_state).toLowerCase()}`;
    await page.screenshot({ path: `screenshots/story-${name}.png`, fullPage: true });

    await page.getByRole("button", { name: "Case details" }).click();
    const sheet = page.getByRole("dialog");
    if (result.investigation_log) await expect(sheet.getByTestId("investigation-steps")).toBeVisible();
    if (degraded.length && !snapshot) {
      await expect(sheet.getByTestId("investigation-steps")).toContainText(
        /no diagnosis was substituted/,
      );
      await expect(sheet.getByTestId("investigator-findings")).toHaveCount(0);
    }
    if (detail.diagnosis.reason === "review_not_accepted") {
      await expect(sheet.getByTestId("investigator-findings")).toContainText(
        "not accepted by the reviewer",
      );
      await expect(sheet).toContainText("did not accept the investigation");
    }
    if (execution?.status === "NOT_ACKNOWLEDGED")
      await expect(sheet).toContainText("nothing was carried out");
    if (outcome && outcome.current_cycle === false) {
      // An earlier cycle's outcome is history, never the current action's outcome.
      await expect(sheet.getByTestId("verification-result")).toHaveCount(0);
      await expect(sheet.getByTestId("earlier-outcome")).toContainText(outcome.reason);
    } else if (outcome) {
      const verification = sheet.getByTestId("verification-result");
      await verification.scrollIntoViewIfNeeded();
      await expect(verification).toContainText(outcome.reason);
      if (outcome.outcome_type === "no_confirming_evidence")
        await expect(verification).toContainText("Delivered · no answer by the deadline");
    } else await expect(sheet.getByTestId("verification-result")).toHaveCount(0);
    await page.screenshot({ path: `screenshots/story-${name}-assessment.png` });
    // The assessment sheet never scrolls sideways: long identifiers wrap.
    expect(
      await sheet.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
    ).toBe(true);
    await page.keyboard.press("Escape");

    // The Resolved queue holds this case only if the backend resolved it from a verified outcome.
    const resolved =
      detail.workflow_state === "RESOLVED" &&
      outcome?.success === true &&
      outcome?.exception_cleared !== false;
    await page.goto("/app/operations");
    await expect(page.locator(".environment-badge")).toHaveText("Connected", {
      timeout: 60000,
    });
    await page.getByRole("button", { name: "Expand resolved panel" }).click();
    const rail = page.getByLabel("Verified resolutions");
    if (resolved) {
      await expect(rail).toContainText(detail.shipment_id, { timeout: 30000 });
      await page.screenshot({ path: "screenshots/story-resolved-queue.png" });
    } else await expect(rail).not.toContainText(detail.shipment_id);
    expect(errors).toEqual([]);
  });
