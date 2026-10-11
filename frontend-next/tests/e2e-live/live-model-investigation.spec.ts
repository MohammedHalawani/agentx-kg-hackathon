import { expect, test } from "@playwright/test";

/**
 * One real GPT-OSS investigation, started and watched through the interface. This makes real
 * model calls (capped per case by the backend), so it runs only when SUHAIL_LIVE_MODEL=1 and
 * the backend was started with its investigator on (scripts/ui_scratch_backend.py with
 * SUHAIL_UI_AGENTS=on). Scratch or demo database only.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8010 SUHAIL_LIVE_MODEL=1 npx playwright test \
 *     --config playwright.live.config.ts live-model-investigation
 *
 * SUHAIL_LIVE_CASE=<case id> picks the case; otherwise the oldest queued case is used.
 */
test.skip(process.env.SUHAIL_LIVE_MODEL !== "1", "set SUHAIL_LIVE_MODEL=1 (real model calls)");
test.setTimeout(15 * 60 * 1000);

test("A queued case is investigated by the real investigator and the interface shows what it did", async ({
  page,
  request,
}) => {
  const status = await (await request.get("/worker/status")).json();
  expect(String(status.database)).toMatch(/-(ui|test2?|ci-test)$|^shipments-v2-world-demo/);
  const rows = (await (await request.get("/cases/queue?scope=all&limit=100")).json()).items as {
    case_id: string;
    shipment_id: string;
    workflow_state: string;
  }[];
  const row = process.env.SUHAIL_LIVE_CASE
    ? rows.find((item) => item.case_id === process.env.SUHAIL_LIVE_CASE)
    : rows.filter((item) => item.workflow_state === "OPEN").at(0);
  test.skip(!row, "no queued case to investigate");
  await page.goto(`/app/cases/${row!.case_id}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(row!.shipment_id, {
    timeout: 30000,
  });
  await page.getByRole("button", { name: "Investigate now" }).click();
  // Live: the rail shows the investigator's own evidence queries as the backend records them.
  await expect(page.locator(".pipeline-stage-summary")).toContainText(
    /Investigator queried/,
    { timeout: 180000 },
  );
  await page.screenshot({ path: "screenshots/model-investigating.png" });
  // Wait for the backend to finish the run (reviewed, or sent to a person).
  await expect
    .poll(
      async () => {
        const detail = await (await request.get(`/cases/${row!.case_id}`)).json();
        return detail.workflow_state;
      },
      { timeout: 12 * 60 * 1000, intervals: [3000] },
    )
    .not.toMatch(/^(OPEN|INVESTIGATING)$/);
  const detail = await (await request.get(`/cases/${row!.case_id}`)).json();
  const log = detail.run.result.investigation_log;
  expect(detail.run.result.mode).toBe("gpt_oss_agents");
  await expect(page.locator(".case-heading")).not.toContainText("Investigating", {
    timeout: 30000,
  });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "screenshots/model-investigated.png" });
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  const steps = sheet.getByTestId("investigation-steps");
  // The steps listed are exactly the run record's tool calls, and the budget is the record's.
  const calls = (log.rounds as { tool_calls: unknown[] }[]).reduce(
    (sum, round) => sum + round.tool_calls.length,
    0,
  );
  await expect(steps.locator(".investigation-steps li")).toHaveCount(calls);
  await expect(steps).toContainText(
    `${log.model_calls_used} of ${log.model_call_cap} model calls`,
  );
  await expect(sheet.getByTestId("authority-decision")).toContainText(
    detail.run.result.authority.rule_id,
  );
  if (detail.diagnosis.available)
    await expect(sheet.getByTestId("investigator-findings")).not.toContainText(
      "not accepted by the reviewer",
    );
  await page.screenshot({ path: "screenshots/model-assessment.png" });
  await steps.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "screenshots/model-steps.png" });
  test.info().annotations.push({
    type: "model",
    description: `${row!.case_id}: ${detail.workflow_state}, ${log.model_calls_used} model calls, ${calls} tool calls, diagnosis ${detail.diagnosis.available ? detail.diagnosis.primary_cause : `absent (${detail.diagnosis.reason})`}, authority ${detail.run.result.authority.rule_id}`,
  });
  console.log(test.info().annotations.at(-1)!.description);
});
