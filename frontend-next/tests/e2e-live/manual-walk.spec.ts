import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The operator's manual path on a session whose automatic worker is off: pick a waiting case
 * on Operations, click Investigate now, watch the real run with its narration, inspect the
 * evidence and the reviewer's decision, approve where the backend asks for it, watch execution
 * and verification on the running clock, then ask Canopus. Writes to the session it runs on,
 * so it needs SUHAIL_MANUAL_WALK=1 and is meant for the isolated backend only.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8021 SUHAIL_MANUAL_WALK=1 npx playwright test \
 *     --config playwright.live.config.ts manual-walk
 */
test.skip(process.env.SUHAIL_MANUAL_WALK !== "1", "set SUHAIL_MANUAL_WALK=1 (isolated backend)");
test.skip(
  /:8020\b/.test(process.env.SUHAIL_LIVE_URL ?? ""),
  "never on the main backend: this walk starts investigations and approves",
);
const LIMIT = Number(process.env.SUHAIL_MANUAL_CASES ?? 3);
test.setTimeout(55 * 60 * 1000);
const shot = (name: string) => `screenshots/graph/manual-${name}.png`;

interface Detail {
  workflow_state: string;
  shipment_id: string;
  state_version: number;
  recommendation: { approvable?: boolean; action_type?: string; action_en?: string } | null;
  executions: { status: string; authority: string }[];
  outcome: { verification_status: string; success: boolean | null; outcome_type: string; reason: string } | null;
  review: { verdict?: string | null } | null;
  narration: { events: { kind: string }[] } | null;
  next_step: { code: string; text_en: string } | null;
  run: { result: { authority?: { rule_id?: string } } } | null;
}
const read = async (request: APIRequestContext, id: string) =>
  (await (await request.get(`/cases/${id}`)).json()) as Detail;
const queue = async (request: APIRequestContext) =>
  ((await (await request.get("/cases/queue?scope=all&limit=100")).json()) as {
    items: { case_id: string; shipment_id: string; workflow_state: string }[];
  }).items;

async function askCanopus(page: Page, question: string) {
  const panel = page.locator(".canopus-window");
  if (!(await panel.isVisible().catch(() => false)))
    await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const before = await panel.getByTestId("canopus-answer").count();
  await panel.getByRole("textbox", { name: "Ask Canopus about this case" }).fill(question);
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(before + 1, { timeout: 120000 });
  return panel;
}

test("An operator selects a waiting case, investigates it, approves where asked, and asks Canopus", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const status = await (await request.get("/worker/status")).json();
  console.log(`worker ${status.worker.state}; clock ${status.simulator?.state} at speed ${status.simulator?.speed}`);
  // 1. Operations lists the waiting exceptions; automatic investigation is off.
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Connected", { timeout: 90000 });
  await expect(page.getByRole("switch", { name: "Automatic investigation" })).not.toBeChecked();
  await page.waitForTimeout(2500);
  await page.screenshot({ path: shot("1-operations") });
  const begun = Date.now();
  const arrivalsUntil = begun + Number(process.env.SUHAIL_MANUAL_MINUTES ?? 0) * 60 * 1000 + 15000;
  const walked: string[] = [];
  let approved: string | null = null;
  for (let round = 0; round < LIMIT; round++) {
    // Cases may still be arriving: wait for the next one to open, within the time allowed.
    let waiting: Awaited<ReturnType<typeof queue>> = [];
    while (Date.now() < arrivalsUntil) {
      waiting = (await queue(request)).filter(
        (row) => row.workflow_state === "OPEN" && !walked.includes(row.case_id),
      );
      if (waiting.length) break;
      await page.waitForTimeout(8000);
    }
    if (!waiting.length) break;
    console.log(`+${Math.round((Date.now() - begun) / 1000)}s selecting ${waiting[0].shipment_id}`);
    const row = waiting[0];
    walked.push(row.case_id);
    // 2. Select it.
    await page.goto("/app/operations");
    await page.getByRole("textbox", { name: "Search exception queue" }).fill(row.shipment_id);
    await page.getByTestId(`data-row-${row.case_id}`).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(row.shipment_id, {
      timeout: 60000,
    });
    await expect(page.locator(".case-heading")).toContainText("Queued");
    if (round === 0) await page.screenshot({ path: shot("2-selected"), fullPage: true });
    // 3. Investigate, deliberately.
    const started = Date.now();
    await page.getByRole("button", { name: "Investigate now" }).click();
    // 4. Watch the real run: stages and narration as they arrive.
    const seen = new Set<string>();
    let liveNarration = 0;
    let captured = false;
    for (;;) {
      const detail = await read(request, row.case_id);
      // No step is running once the run has ended: never wait for one.
      const running = await page
        .locator(".pipeline-step.state-running")
        .first()
        .getAttribute("aria-label", { timeout: 1000 })
        .catch(() => null);
      if (running) seen.add(running.split(" · ")[0]);
      const told = await page.getByTestId("narration-bubble").count();
      liveNarration = Math.max(liveNarration, told);
      if (!captured && told >= 2 && detail.workflow_state === "INVESTIGATING") {
        captured = true;
        await page.screenshot({ path: shot(`3-investigating-${row.shipment_id}`), fullPage: true });
      }
      if (!/^(OPEN|REOPENED|INVESTIGATING)$/.test(detail.workflow_state)) break;
      if (Date.now() - started > 10 * 60 * 1000) throw new Error("investigation did not finish");
      await page.waitForTimeout(2000);
    }
    await page.waitForTimeout(6000);
    let detail = await read(request, row.case_id);
    console.log(
      `${row.shipment_id}: investigated in ${Math.round((Date.now() - started) / 1000)} s -> ${detail.workflow_state}; rule ${detail.run?.result.authority?.rule_id}; review ${detail.review?.verdict}; steps seen running: ${[...seen].join(", ") || "none sampled"}; narration bubbles seen while running: ${liveNarration}; stored narration: ${detail.narration?.events.length ?? 0}; next: ${detail.next_step?.code}`,
    );
    await expect(page.getByTestId("next-step")).toContainText(detail.next_step!.text_en, {
      timeout: 30000,
    });
    await page.screenshot({ path: shot(`4-investigated-${row.shipment_id}`), fullPage: true });
    // 5. Inspect the evidence and the reviewer's decision.
    await page.getByRole("button", { name: "Case details" }).click();
    const sheet = page.getByRole("dialog");
    if (detail.review?.verdict) await expect(sheet.getByTestId("review-rounds")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.getByTestId("knowledge-graph").locator(".entity-node").nth(2).click();
    await expect(page.getByTestId("evidence-inspector")).toBeVisible();
    // 6. Approve an action where the backend asks for it.
    if (!approved && detail.recommendation?.approvable && detail.workflow_state !== "AWAITING_OUTCOME") {
      // Through Canopus's offer first, which only opens the existing dialog.
      const panel = await askCanopus(page, "Can you request this evidence for me?");
      const door = panel.getByRole("button", { name: "Open Review & authorize" }).last();
      const viaOffer = (await door.count()) > 0;
      if (viaOffer) await door.click();
      else {
        await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
        await page.getByRole("button", { name: "Review & authorize" }).click();
      }
      const dialog = page.getByRole("dialog").filter({ hasText: "Authorize action" });
      await expect(dialog).toContainText(detail.recommendation.action_en!);
      await page.screenshot({ path: shot(`5-approve-${row.shipment_id}`) });
      await dialog.getByRole("button", { name: "Authorize action" }).click();
      await expect(dialog).toHaveCount(0, { timeout: 60000 });
      await expect
        .poll(
          async () =>
            (await read(request, row.case_id)).executions.filter(
              (item) => item.authority === "OPERATOR_APPROVAL",
            ).length,
          { timeout: 90000 },
        )
        .toBeGreaterThan(0);
      detail = await read(request, row.case_id);
      approved = row.case_id;
      console.log(
        `${row.shipment_id}: approved ${detail.recommendation?.action_type} ${viaOffer ? "through Canopus's offer and the dialog" : "through Review & authorize"} -> ${detail.workflow_state}; execution ${detail.executions[0].status}`,
      );
    }
  }
  expect(walked.length).toBeGreaterThan(0);
  // 7. Execution and verification arrive on the running clock, for whichever case acted.
  const acted: string[] = [];
  for (const id of walked) if ((await read(request, id)).executions.length) acted.push(id);
  const deadline = Date.now() + 8 * 60 * 1000;
  const pending = new Set(acted);
  while (pending.size && Date.now() < deadline) {
    for (const id of [...pending]) {
      const detail = await read(request, id);
      if (detail.outcome || detail.workflow_state !== "AWAITING_OUTCOME") pending.delete(id);
    }
    await page.waitForTimeout(5000);
  }
  for (const id of walked) {
    const detail = await read(request, id);
    console.log(
      `${detail.shipment_id}: final ${detail.workflow_state}; executions ${detail.executions.map((item) => `${item.status}/${item.authority}`).join(", ") || "none"}; outcome ${detail.outcome ? `${detail.outcome.verification_status} success ${detail.outcome.success} ${detail.outcome.outcome_type}` : "none"}`,
    );
  }
  // 8. Ask Canopus what happened, on the case that went furthest.
  const target = approved ?? acted[0] ?? walked[0];
  const last = await read(request, target);
  await page.goto(`/app/cases/${target}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(last.shipment_id, {
    timeout: 60000,
  });
  await expect(page.getByTestId("next-step")).toContainText(last.next_step!.text_en, {
    timeout: 60000,
  });
  await page.screenshot({ path: shot(`6-outcome-${last.shipment_id}`), fullPage: true });
  const panel = await askCanopus(page, "What happened on this case, and what was verified?");
  console.log(
    `Canopus on ${last.shipment_id}: ${(await panel.getByTestId("canopus-answer").last().innerText()).replace(/\s+/g, " ").slice(0, 500)}`,
  );
  console.log(`quotes shown: ${await panel.getByTestId("canopus-quote").count()}`);
  await page.screenshot({ path: shot(`7-canopus-${last.shipment_id}`) });
  expect(errors).toEqual([]);
});
