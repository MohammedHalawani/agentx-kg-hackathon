import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * One case taken through the whole lifecycle from the interface on the demo backend:
 * investigate (real GPT-OSS calls), approve if the backend asks for approval, then the
 * simulation clock is advanced by the hour so the simulator's answer and the verifier's
 * outcome arrive. The clock is advanced through the API because the redesigned UI has no
 * clock control. Runs only with SUHAIL_LIVE_DEMO_HANDED_OVER=1 and SUHAIL_DEMO_OPEN_CASE.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8020 SUHAIL_LIVE_DEMO_HANDED_OVER=1 \
 *   SUHAIL_DEMO_OPEN_CASE=<case id> npx playwright test --config playwright.live.config.ts demo-own-case
 */
const CASE = process.env.SUHAIL_DEMO_OPEN_CASE;
test.skip(
  !CASE || process.env.SUHAIL_LIVE_DEMO_HANDED_OVER !== "1",
  "set SUHAIL_DEMO_OPEN_CASE and SUHAIL_LIVE_DEMO_HANDED_OVER=1 (real model calls, demo database)",
);
test.setTimeout(25 * 60 * 1000);
const shot = (name: string) => `screenshots/demo-own-${name}.png`;
const read = async (request: APIRequestContext) =>
  (await (await request.get(`/cases/${CASE}`)).json()) as {
    workflow_state: string;
    shipment_id: string;
    state_version: number;
    diagnosis: { available: boolean; primary_cause: string | null; reason: string | null };
    recommendation: { approvable?: boolean; action_en?: string; risk_class?: string } | null;
    executions: { status: string; authority: string }[];
    outcome: { verification_status: string; success: boolean | null; exception_cleared: boolean | null; reason: string } | null;
    run: { result: { authority: { rule_id: string }; investigation_log: { model_calls_used: number } } };
  };

test("A queued case goes from investigation to a verified outcome through the interface", async ({
  page,
  request,
}) => {
  const before = await read(request);
  expect(before.workflow_state).toBe("OPEN");
  await page.goto(`/app/cases/${CASE}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(before.shipment_id, {
    timeout: 60000,
  });
  await page.screenshot({ path: shot("1-detected") });

  // Investigation: real model calls, watched live.
  await page.getByRole("button", { name: "Investigate now" }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(/Investigator queried/, {
    timeout: 240000,
  });
  await page.screenshot({ path: shot("2-investigating") });
  await expect
    .poll(async () => (await read(request)).workflow_state, {
      timeout: 15 * 60 * 1000,
      intervals: [3000],
    })
    .not.toMatch(/^(OPEN|INVESTIGATING)$/);
  let detail = await read(request);
  await page.waitForTimeout(6000);
  await page.screenshot({ path: shot("3-investigated") });
  const notes = [
    `after investigation: ${detail.workflow_state}`,
    `diagnosis ${detail.diagnosis.available ? detail.diagnosis.primary_cause : `absent (${detail.diagnosis.reason})`}`,
    `authority ${detail.run.result.authority?.rule_id}`,
    `${detail.run.result.investigation_log.model_calls_used} model calls`,
  ];

  // Approval, only when the backend offers one.
  if (detail.recommendation?.approvable) {
    await page.getByRole("button", { name: "Review & authorize" }).click();
    await page.screenshot({ path: shot("4-approval") });
    await page.getByRole("dialog").getByRole("button", { name: "Authorize action" }).click();
    await expect
      .poll(async () => (await read(request)).executions.length, { timeout: 60000 })
      .toBeGreaterThan(0);
    notes.push("approved through the interface");
    detail = await read(request);
  }

  // Execution and verification: nothing to call; the clock is advanced so answers arrive.
  if (detail.workflow_state === "AWAITING_OUTCOME") {
    await expect(page.locator(".case-heading")).toContainText("Verifying outcome", {
      timeout: 30000,
    });
    await page.screenshot({ path: shot("5-awaiting-outcome") });
    const token = (await (await request.get("/operations/session")).json()).token;
    for (let hour = 0; hour < 12; hour += 1) {
      detail = await read(request);
      if (detail.workflow_state !== "AWAITING_OUTCOME") break;
      const tick = await request.post("/simulation/tick", {
        data: { seconds: 3600 },
        headers: { "X-Operations-Token": token },
        timeout: 300000,
      });
      expect(tick.ok()).toBe(true);
      await page.waitForTimeout(5000);
    }
    detail = await read(request);
    notes.push(
      `execution ${detail.executions[0]?.status} (${detail.executions[0]?.authority})`,
      detail.outcome
        ? `outcome ${detail.outcome.verification_status} success=${detail.outcome.success} cleared=${detail.outcome.exception_cleared}: ${detail.outcome.reason}`
        : "no outcome yet",
    );
  }
  notes.push(`final ${detail.workflow_state}`);

  // The interface shows the backend's final state, and nothing beyond it.
  await page.waitForTimeout(8000);
  const resolved = detail.workflow_state === "RESOLVED";
  if (resolved) await expect(page.locator(".case-heading")).toContainText("Resolved");
  else await expect(page.locator(".case-heading")).not.toContainText("Resolved");
  await page.screenshot({ path: shot("6-final"), fullPage: true });
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet.getByTestId("investigation-steps")).toBeVisible();
  if (detail.outcome) {
    const verification = sheet.getByTestId("verification-result");
    await verification.scrollIntoViewIfNeeded();
    await expect(verification).toContainText(detail.outcome.reason);
    await page.screenshot({ path: shot("7-verification") });
  }
  await page.keyboard.press("Escape");
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Synthetic data", { timeout: 60000 });
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  const rail = page.getByLabel("Verified resolutions");
  if (resolved) await expect(rail).toContainText(detail.shipment_id, { timeout: 30000 });
  else await expect(rail).not.toContainText(detail.shipment_id);
  await page.screenshot({ path: shot("8-operations") });
  console.log(`${CASE}: ${notes.join(" | ")}`);
});
