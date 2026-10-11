import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * The two operator actions on the demo backend, taken from the interface: approving a
 * recommendation the backend marks approvable, and recording a person's finding on a case that
 * is with a person. Both write to the demo session, so they run only when handed over.
 *
 *   SUHAIL_LIVE_URL=http://127.0.0.1:8020 SUHAIL_LIVE_DEMO_HANDED_OVER=1 \
 *   SUHAIL_DEMO_APPROVE=<case id> SUHAIL_DEMO_FINDING=<case id> \
 *   npx playwright test --config playwright.live.config.ts demo-operator
 */
const APPROVE = process.env.SUHAIL_DEMO_APPROVE;
const FINDING = process.env.SUHAIL_DEMO_FINDING;
const handedOver = process.env.SUHAIL_LIVE_DEMO_HANDED_OVER === "1";
test.setTimeout(5 * 60 * 1000);
const shot = (name: string) => `screenshots/demo-operator-${name}.png`;
const read = async (request: APIRequestContext, id: string) =>
  (await (await request.get(`/cases/${id}`)).json()) as {
    workflow_state: string;
    shipment_id: string;
    state_version: number;
    recommendation: { approvable?: boolean; action_en?: string } | null;
    executions: { status: string; authority: string; deadline_at?: string }[];
    outcome: { verification_status: string; success: boolean | null; reason: string } | null;
  };

test("An approvable recommendation is approved from the interface", async ({ page, request }) => {
  test.skip(!APPROVE || !handedOver, "set SUHAIL_DEMO_APPROVE and SUHAIL_LIVE_DEMO_HANDED_OVER=1");
  const before = await read(request, APPROVE!);
  expect(before.recommendation?.approvable).toBe(true);
  expect(before.executions).toHaveLength(0);
  await page.goto(`/app/cases/${APPROVE}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(before.shipment_id, {
    timeout: 60000,
  });
  await page.getByRole("button", { name: "Review & authorize" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText(before.recommendation!.action_en!);
  await page.screenshot({ path: shot("1-approve-dialog") });
  await dialog.getByRole("button", { name: "Authorize action" }).click();
  await expect(dialog).toHaveCount(0, { timeout: 60000 });
  await expect
    .poll(async () => (await read(request, APPROVE!)).executions.length, { timeout: 60000 })
    .toBeGreaterThan(0);
  const after = await read(request, APPROVE!);
  console.log(
    `approved: ${before.workflow_state} v${before.state_version} -> ${after.workflow_state} v${after.state_version}; execution ${after.executions[0].status} by ${after.executions[0].authority}; deadline ${after.executions[0].deadline_at ?? "none"}`,
  );
  expect(after.executions[0].authority).toBe("OPERATOR_APPROVAL");
  // The page follows the backend: no second approval is offered, and a receipt is not an outcome.
  await expect(page.getByRole("button", { name: "Review & authorize" })).toHaveCount(0, {
    timeout: 30000,
  });
  await page.waitForTimeout(3000);
  await page.screenshot({ path: shot("2-approved"), fullPage: true });
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet).toContainText(
    after.executions[0].status === "ACKNOWLEDGED"
      ? "A receipt is not an outcome"
      : "nothing was carried out",
  );
  if (!after.outcome) await expect(sheet.getByTestId("verification-result")).toHaveCount(0);
  await page.screenshot({ path: shot("3-approved-assessment") });
});

test("A person's finding is recorded from the interface", async ({ page, request }) => {
  test.skip(!FINDING || !handedOver, "set SUHAIL_DEMO_FINDING and SUHAIL_LIVE_DEMO_HANDED_OVER=1");
  const before = await read(request, FINDING!);
  expect(before.workflow_state).toBe("HUMAN_REVIEW");
  await page.goto(`/app/cases/${FINDING}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(before.shipment_id, {
    timeout: 60000,
  });
  await page.getByRole("button", { name: "Record a person's finding" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("combobox", { name: "Human outcome type" }).click();
  await page.getByRole("option", { name: "Parcel not found" }).click();
  await dialog
    .getByLabel("Finding")
    .fill("Interface test entry on synthetic data: no physical check was made; parcel not found.");
  await dialog.locator(".human-evidence [role=checkbox]").first().click();
  await page.screenshot({ path: shot("4-finding-dialog") });
  await dialog.getByRole("button", { name: "Record finding" }).click();
  // Either the backend accepts it and the dialog closes, or its refusal is shown verbatim.
  const refusal = dialog.getByRole("alert");
  await expect(dialog.or(refusal).first()).toBeVisible();
  await Promise.race([
    expect(dialog).toHaveCount(0, { timeout: 60000 }),
    expect(refusal).toBeVisible({ timeout: 60000 }),
  ]);
  const after = await read(request, FINDING!);
  if (await refusal.isVisible().catch(() => false)) {
    console.log(`finding refused by the backend: ${await refusal.innerText()}`);
    await page.screenshot({ path: shot("5-finding-refused") });
    expect(after.state_version).toBe(before.state_version);
    return;
  }
  console.log(
    `finding recorded: ${after.workflow_state} v${after.state_version}; outcome ${after.outcome?.verification_status} success ${after.outcome?.success}`,
  );
  expect(after.outcome?.verification_status).toMatch(/^HUMAN_/);
  // A parcel that was not found never resolves the case.
  expect(after.workflow_state).not.toBe("RESOLVED");
  await page.getByRole("button", { name: "Case details" }).click();
  const verification = page.getByRole("dialog").getByTestId("verification-result");
  await verification.scrollIntoViewIfNeeded();
  await expect(verification).toContainText("Finding on record · not resolved");
  await page.screenshot({ path: shot("5-finding-recorded") });
});
