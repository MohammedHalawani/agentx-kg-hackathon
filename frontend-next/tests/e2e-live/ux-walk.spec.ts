import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * The simplified operator experience, walked on an isolated backend: for each named shipment,
 * select it, click Investigate now, watch the connected pipeline, read the one assessment,
 * skip the simulated wait, and ask Canopus. Everything asserted is compared with the backend's
 * own record. It starts investigations and skips simulated time, so it needs SUHAIL_UX_WALK=1
 * and refuses the two backends the operator uses.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8022 SUHAIL_UX_WALK=1 \
 *   SUHAIL_UX_SHIPMENTS=SYN-SHP-000375,SYN-SHP-000058,SYN-SHP-000232 \
 *   npx playwright test --config playwright.live.config.ts ux-walk
 */
const SHIPMENTS = (process.env.SUHAIL_UX_SHIPMENTS ?? "").split(",").filter(Boolean);
test.skip(process.env.SUHAIL_UX_WALK !== "1" || !SHIPMENTS.length, "set SUHAIL_UX_WALK=1 and SUHAIL_UX_SHIPMENTS");
test.skip(
  /:802[01]\b/.test(process.env.SUHAIL_LIVE_URL ?? ""),
  "never on the operator's backends: this walk investigates and skips simulated time",
);
test.setTimeout(45 * 60 * 1000);
const shot = (name: string) => `screenshots/graph/ux-${name}.png`;
const CODES = /\b(AUTH-\d|LIFECYCLE-|AWAITING_[A-Z]|HUMAN_REVIEW|REQUEST_[A-Z]|SYN-OPS-)/;

interface Detail {
  case_id: string;
  workflow_state: string;
  shipment_id: string;
  brief: {
    resolved: boolean;
    waiting_kind: string;
    lines: { key: string; text_en: string }[];
    review?: { status?: string };
    verification?: { status?: string; text_en?: string };
    actions?: { status?: string; outcome?: unknown }[];
  } | null;
  outcome: { verification_status: string; success: boolean | null; outcome_type: string } | null;
  executions: { status: string }[];
  next_step: { text_en: string } | null;
  pipeline: { stage_facts?: { stage: string; fact_en?: string; status?: string }[] };
}
const read = async (request: APIRequestContext, id: string) =>
  (await (await request.get(`/cases/${id}`)).json()) as Detail;

test("Each shipment is investigated by a click and reads as one clear assessment", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/app/operations");
  await expect(page.locator(".environment-badge")).toHaveText("Connected", { timeout: 90000 });
  await expect(page.getByRole("switch", { name: "Automatic investigation" })).not.toBeChecked();
  // Start the clock first: nothing can arrive while it is paused.
  const clock = page.getByTestId("clock-control");
  if (/paused/i.test(await clock.innerText())) await clock.click();
  await expect(clock).toContainText("running", { timeout: 20000 });
  await page.screenshot({ path: shot("0-operations") });

  for (const shipment of SHIPMENTS) {
    const tag = shipment.slice(-3);
    // Wait for the case to be in the queue (it may open as the clock runs), then select it.
    let row: { case_id: string; workflow_state: string } | undefined;
    await expect
      .poll(
        async () => {
          const items = (
            (await (await request.get("/cases/queue?scope=all&limit=100")).json()) as {
              items: { case_id: string; shipment_id: string; workflow_state: string }[];
            }
          ).items;
          row = items.find((item) => item.shipment_id === shipment);
          return row?.workflow_state ?? "absent";
        },
        { timeout: 20 * 60 * 1000, intervals: [5000] },
      )
      .not.toBe("absent");
    // A case already investigated in an earlier pass is only read, not investigated again.
    const fresh = /^(OPEN|REOPENED)$/.test(row!.workflow_state);
    const id = row!.case_id;
    await page.goto("/app/operations");
    await page.getByRole("textbox", { name: "Search exception queue" }).fill(shipment);
    await page.getByTestId(`data-row-${id}`).click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(shipment, { timeout: 60000 });
    // The sidebar folds to give the case room.
    await expect(page.locator(".brand-star")).toBeVisible();
    const started = Date.now();
    if (fresh) await page.getByRole("button", { name: "Investigate now" }).click();
    let sawRunning = false;
    let captured = false;
    for (;;) {
      const detail = await read(request, id);
      const running = await page.locator(".pipeline-step.state-running").count();
      if (running) sawRunning = true;
      if (running && !captured && Date.now() - started > 12000) {
        captured = true;
        await page.screenshot({ path: shot(`${tag}-1-investigating`), clip: { x: 0, y: 0, width: 1440, height: 700 } });
      }
      if (!/^(OPEN|REOPENED|INVESTIGATING)$/.test(detail.workflow_state)) break;
      if (Date.now() - started > 8 * 60 * 1000) throw new Error(`${shipment}: investigation did not finish`);
      await page.waitForTimeout(2000);
    }
    let detail = await read(request, id);
    const seconds = Math.round((Date.now() - started) / 1000);
    // One assessment, in the backend's words, with no internal codes on the main page.
    const assessment = page.getByTestId("case-assessment");
    await expect(assessment).toBeVisible({ timeout: 45000 });
    await expect
      .poll(async () => (await assessment.innerText()).includes((await read(request, id)).brief!.lines[0].text_en), { timeout: 30000 })
      .toBe(true);
    detail = await read(request, id);
    for (const line of detail.brief!.lines) await expect(assessment).toContainText(line.text_en);
    expect(CODES.test((await assessment.locator("dl").innerText()))).toBe(false);
    await expect(page.locator(".pipeline-stages.connected")).toBeVisible();
    await expect(page.locator(".pipeline-step.state-failed")).toHaveCount(
      detail.executions[0]?.status === "NOT_ACKNOWLEDGED" ? 1 : 0,
    );
    // No narration cards on the main page unless the operator opens the commentary.
    await expect(page.locator(".narration-strip").getByTestId("narration-bubble")).toHaveCount(0);
    await expect(page.getByTestId("next-step")).toContainText(detail.next_step!.text_en);
    console.log(
      `${shipment}: investigated in ${seconds} s -> ${detail.workflow_state} (${detail.brief!.waiting_kind}); review ${detail.brief!.review?.status}; saw a running step: ${sawRunning}`,
    );
    for (const line of detail.brief!.lines) console.log(`   ${line.key}: ${line.text_en}`);
    await page.screenshot({ path: shot(`${tag}-2-assessment`), fullPage: true });

    // The wait for an answer: skip simulated time until this case is decided (a few tries).
    for (let skip = 0; skip < 5 && detail.workflow_state === "AWAITING_OUTCOME"; skip++) {
      await page.goto("/app/operations");
      const button = page.getByTestId("clock-skip");
      await expect(button).toBeEnabled({ timeout: 60000 });
      const began = Date.now();
      await button.click();
      const toast = page.locator("[data-sonner-toast]").last();
      // A skip the backend could not complete says so; it is noted and tried again.
      await expect(toast).toContainText(/Skipped|unavailable|running/, { timeout: 6 * 60 * 1000 });
      console.log(`   skip ${skip + 1} (${Math.round((Date.now() - began) / 1000)} s): ${(await toast.innerText()).replace(/\s+/g, " ")}`);
      await page.waitForTimeout(4000);
      detail = await read(request, id);
    }
    await page.goto(`/app/cases/${id}`);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(shipment, { timeout: 60000 });
    await expect(assessment).toContainText(detail.brief!.lines.at(-1)!.text_en, { timeout: 45000 });
    // Resolved on screen exactly when the backend's record says resolved.
    await expect(page.locator(".case-heading")).toContainText(
      detail.brief!.resolved ? "Resolved" : /Human investigation|Escalated|Verifying outcome|Awaiting approval/,
    );
    console.log(
      `   end: ${detail.workflow_state}; resolved ${detail.brief!.resolved}; verification ${detail.brief!.verification?.status}; outcome ${detail.outcome ? `${detail.outcome.verification_status} success ${detail.outcome.success} ${detail.outcome.outcome_type}` : "none"}`,
    );
    console.log(`   status line: ${detail.brief!.lines.at(-1)!.text_en}`);
    await page.screenshot({ path: shot(`${tag}-3-end`), fullPage: true });
    // The full assessment: the seven questions, technical record folded.
    await page.getByRole("button", { name: "Case details" }).click();
    const sheet = page.getByRole("dialog");
    await expect(sheet.getByTestId("assessment-answers")).toContainText("Is the shipment issue resolved?");
    await expect(sheet.getByTestId("assessment-answers")).toContainText(
      detail.brief!.resolved ? "Yes · independently verified" : "No · not resolved",
    );
    await expect(sheet.getByTestId("technical-record")).not.toHaveAttribute("open", "");
    await page.screenshot({ path: shot(`${tag}-4-full-assessment`) });
    await page.keyboard.press("Escape");
    // Canopus as a chat: one question, one readable answer, no codes, no automatic cards.
    await page.getByRole("button", { name: "Open Canopus assistant" }).click();
    const panel = page.locator(".canopus-window");
    await expect(panel.getByTestId("canopus-answer")).toHaveCount(0);
    await panel.getByRole("textbox", { name: "Ask Canopus about this case" }).fill(
      detail.brief!.resolved ? "What proved that this is resolved?" : "What is Suhail waiting for, and who needs to act next?",
    );
    await panel.getByRole("button", { name: "Send question" }).click();
    const answer = panel.getByTestId("canopus-answer");
    await expect(answer).toHaveCount(1, { timeout: 120000 });
    const text = await answer.locator(".chat-prose").innerText();
    console.log(`   Canopus: ${text.replace(/\s+/g, " ").slice(0, 420)}`);
    expect(CODES.test(text), `codes in the answer: ${text}`).toBe(false);
    await expect(answer.getByTestId("canopus-quote")).toHaveCount(0);
    await expect(answer).not.toContainText("Not available");
    // Asked for the original message: quoted in the answer, labelled with its source.
    const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
    await box.fill("Show me the investigator's original message.");
    await panel.getByRole("button", { name: "Send question" }).click();
    await expect(panel.getByTestId("canopus-answer")).toHaveCount(2, { timeout: 120000 });
    const second = panel.getByTestId("canopus-answer").nth(1);
    console.log(
      `   original message: ${await second.getByTestId("canopus-quote").count()} quote(s) shown; ${(await second.innerText()).replace(/\s+/g, " ").slice(0, 260)}`,
    );
    // Asked why an approval is not possible: a plain reason, no rule id.
    await box.fill("Why can't I approve this?");
    await panel.getByRole("button", { name: "Send question" }).click();
    await expect(panel.getByTestId("canopus-answer")).toHaveCount(3, { timeout: 120000 });
    const third = panel.getByTestId("canopus-answer").nth(2);
    const why = (await third.innerText()).replace(/\s+/g, " ");
    console.log(`   why not approve: ${why.slice(0, 360)}`);
    expect(/AUTH-\d|LIFECYCLE-/.test(why), why).toBe(false);
    await page.screenshot({ path: shot(`${tag}-5-chat`) });
    await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
  }
  expect(errors).toEqual([]);
});
