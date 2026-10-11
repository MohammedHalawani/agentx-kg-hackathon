import { expect, test } from "@playwright/test";
import { CASE_A, SHIP_A } from "../fixtures/backend";
import { stubBackend } from "./backend-stub";

const LAB_ONLY = /SHP-10482|Noura Al-Salem|UI lab|Local simulation|policy C-04/;

test("Operations shows the backend queue with real identities and honest labels", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto("/app/");
  await expect(page).toHaveURL(/\/app\/operations$/);
  const rows = page.locator("[data-testid^='data-row-']");
  await expect(rows).toHaveCount(2);
  // Newest first; the shipment id is shown, the link is the case.
  await expect(rows.first()).toContainText("SYN-SHP-000103");
  await expect(rows.first()).toContainText("Recipient reported not received");
  await expect(rows.first()).toContainText("Queued");
  await expect(rows.first()).toContainText("Not set");
  const reviewed = page.getByTestId(`data-row-${CASE_A}`);
  await expect(reviewed).toContainText(SHIP_A);
  await expect(reviewed).toContainText("Riyadh");
  await expect(reviewed).toContainText("Dammam");
  await expect(reviewed).toContainText("Awaiting approval");
  await expect(reviewed).toContainText("Unreconciled custody");
  await expect(page.locator(".environment-badge")).toHaveText("Connected");
  await expect(page.locator(".sidebar-system")).toContainText("Backend connected");
  await expect(page.locator(".operator-button")).toContainText("SYN-OPERATOR-LOCAL");
  // Demo-facing cleanup: no workspace card, no visible dataset wording, the logo alone.
  await expect(page.locator(".workspace-selector")).toHaveCount(0);
  await expect(page.locator(".brand-logo .brand-full")).toBeVisible();
  await expect(page.locator(".brand-header")).toHaveText("");
  await expect(page.locator("body")).not.toContainText(/synthetic/i);
  await expect(page.locator(".environment-badge")).toHaveAttribute("data-dataset", "synthetic");
  await expect(page.locator("body")).not.toContainText(LAB_ONLY);
  // Only the independently verified case is in Resolved.
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  const resolved = page.getByLabel("Verified resolutions");
  await expect(resolved.locator(".resolved-entry")).toHaveCount(1);
  await expect(resolved).toContainText("SYN-SHP-000102");
  // Filters work on the loaded queue; the cause list holds accepted diagnoses only.
  await page.getByRole("textbox", { name: "Search exception queue" }).fill("000103");
  await expect(rows).toHaveCount(1);
});

test("An unreachable backend shows nothing and says so; no stand-in data appears", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  stub.state.online = false;
  await page.goto("/app/operations");
  await expect(page.locator(".backend-notice")).toContainText(
    "The Suhail backend is not reachable",
  );
  await expect(page.locator("[data-testid^='data-row-']")).toHaveCount(0);
  await expect(page.locator(".operations-ledger")).toContainText(
    "The Suhail backend is not reachable",
  );
  await expect(page.locator(".environment-badge")).toHaveText("Backend offline");
  await expect(page.locator("body")).not.toContainText(LAB_ONLY);
  // When it answers again the queue appears without a reload.
  stub.state.online = true;
  await expect(page.locator("[data-testid^='data-row-']")).toHaveCount(2, {
    timeout: 15000,
  });
  await expect(page.locator(".backend-notice")).toHaveCount(0);
});

test("Investigation shows recorded evidence, keeps GPS apart from custody, and relays an approval without resolving anything", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  // A direct link works after a reload: the case is read from the backend, not from a list.
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await expect(page.locator(".case-heading")).toContainText("Awaiting approval");
  // Map: two confirmed custody points, bounded vehicle telemetry, one recorded attempt.
  const map = page.getByTestId("route-map");
  await expect(map.locator(".evidence-marker.confirmed")).toHaveCount(2);
  await expect(map.locator(".evidence-marker.vehicle_only")).toHaveCount(6);
  await expect(page.locator(".case-context")).toContainText("SYN-DEPOT-DMM-01");
  await expect(page.locator(".case-context")).toContainText(
    "Request depot reconciliation scan",
  );
  await expect(page.locator(".case-context")).toContainText(
    "Operator approval required",
  );
  // Graph: bounded, and it says so.
  // The graph opens focused on the shipment; every drawn node is a real record, and the whole
  // bounded set is one click away.
  const graphNodes = page.getByTestId("knowledge-graph").locator(".entity-node");
  await expect(graphNodes.first()).toBeVisible();
  const all = page.getByRole("button", { name: /^All \d+ records$/ });
  const total = Number((await all.innerText()).match(/\d+/)![0]);
  expect(await graphNodes.count()).toBeLessThan(total);
  await all.click();
  await expect(graphNodes).toHaveCount(total);
  await page.getByRole("button", { name: "Focused view" }).click();
  await expect(page.locator(".workspace-toolbar")).toContainText(
    /graph draws from \d+ of \d+ recorded nodes/,
  );
  // A recorded stage shows the reviewer's own verdict and highlights what the stage cited.
  await page.getByRole("button", { name: /^Review ·/ }).click();
  await expect(page.locator(".pipeline-stage-summary")).toContainText(
    "Independent reviewer: accept",
  );
  await page.getByRole("button", { name: /^Diagnose ·/ }).click();
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "Custody · Loaded",
  );
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "CONFIRMED CUSTODY",
  );
  // Vehicle telemetry is labelled as such.
  // Markers can overlap at this zoom; deliver the click to the marker itself.
  await map.locator(".evidence-marker.vehicle_only").last().dispatchEvent("click");
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "VEHICLE TELEMETRY ONLY",
  );

  // Approval: no reason is collected (the backend stores none), and the request is exact.
  await page.getByRole("button", { name: "Review & authorize" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByLabel("Decision reason")).toBeDisabled();
  await expect(dialog).toContainText("does not store decision reasons yet");
  await dialog.getByRole("button", { name: "Authorize action" }).click();
  await expect(dialog).toBeHidden();
  expect(stub.posts).toHaveLength(1);
  expect(stub.posts[0].path).toBe(`/cases/${CASE_A}/decision`);
  expect(stub.posts[0].token).toBe("test-token-0123456789");
  expect(Object.keys(stub.posts[0].body).sort()).toEqual([
    "decision",
    "expected_version",
    "idempotency_key",
  ]);
  expect(stub.posts[0].body).toMatchObject({
    decision: "approve",
    expected_version: 7,
  });
  // The backend authorized an execution. The case is not resolved and is not shown as such.
  await expect(page.locator(".case-heading")).toContainText("Verifying outcome");
  await expect(page.locator(".case-context")).toContainText(
    "Ask the verifier to check now",
  );
  await expect(page.getByRole("button", { name: "Review & authorize" })).toHaveCount(0);
  await page.getByRole("button", { name: "Case details" }).click();
  const sheet = page.getByRole("dialog");
  await expect(sheet).toContainText("A receipt is not an outcome");
  await expect(sheet).toContainText("Independent review");
  // What the investigation did, from the run record: queries, budget, review, authority.
  const steps = sheet.getByTestId("investigation-steps");
  await expect(steps.locator(".investigation-steps li")).toHaveCount(3);
  await expect(steps).toContainText("6 of 12 model calls");
  await expect(steps).toContainText("2 records from beyond this shipment");
  await expect(steps.locator(".finding-cross")).toHaveCount(1);
  await expect(steps).toContainText("not treated as absence of evidence");
  await expect(sheet.getByTestId("review-rounds")).toContainText("Independent model review · round 1");
  await expect(sheet.getByTestId("authority-decision")).toContainText("AUTH-11-approval-required");
  // The investigator's hypotheses with their status and cited evidence; rule checks labelled.
  const findings = sheet.getByTestId("investigator-findings");
  await expect(findings).toContainText("Investigator's findings");
  await expect(findings.locator(".finding-supported")).toHaveText("Supported");
  await expect(findings.locator(".finding-refuted")).toHaveText("Refuted");
  await expect(findings).toContainText("Missing evidence");
  await expect(findings).toContainText("6 evidence queries");
  await expect(
    findings.getByRole("button", { name: "SHP-000101-SCAN-HIDDEN" }),
  ).toBeDisabled();
  await expect(sheet.getByTestId("rule-signals")).toContainText(
    "Rule checks · not a diagnosis",
  );
  const citation = findings.getByRole("button", { name: "SHP-000101-CUST-02-01" });
  await citation.scrollIntoViewIfNeeded();
  await expect(citation).toBeEnabled();
  await citation.click();
  await expect(page.getByTestId("evidence-inspector")).toContainText(
    "Custody · Loaded",
  );
  await page.getByRole("button", { name: "Case details" }).click();
  await expect(sheet).not.toContainText("resolved");
  await page.keyboard.press("Escape");
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Expand resolved panel" }).click();
  await expect(
    page.getByLabel("Verified resolutions").locator(".resolved-entry"),
  ).toHaveCount(1);
});

test("A link that carries a shipment id opens that shipment's case", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${SHIP_A}`);
  await expect(page).toHaveURL(new RegExp(`/app/cases/${CASE_A}$`));
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
});

test("A case the backend does not have is reported, not rendered", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto("/app/cases/SYN-CASE-DOES-NOT-EXIST");
  await expect(page.locator(".empty-state")).toContainText("Case not available");
  await expect(page.locator(".empty-state")).toContainText("not found");
});

test("Canopus answers about the open case with its sources kept apart, and offers only the existing approval path", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const panel = page.locator(".canopus-window");
  await expect(panel).toContainText("performs no action");
  const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
  await box.fill("What did the reviewer say?");
  await panel.getByRole("button", { name: "Send question" }).click();
  // Canopus's own text, labelled as the model's.
  const answer = panel.getByTestId("canopus-answer");
  await expect(answer).toHaveAttribute("data-kind", "canopus_answer");
  await expect(answer).toContainText("Canopus answer");
  await expect(answer).toContainText("The reviewer accepted the finding");
  await expect(answer).toContainText("Show 1 records in the graph");
  // The reviewer's recorded message: source material, never Canopus's words.
  const quote = panel.getByTestId("canopus-quote");
  await expect(quote).toContainText("Reviewer's own words");
  await expect(quote).toContainText("recorded message, not rewritten");
  await expect(quote).toContainText("Citations are valid and support the conclusion.");
  await expect(quote).toContainText("OPS-REVIEW-A");
  // What the rules allow: a refused offer says why; an allowed one opens the existing dialog.
  const offers = panel.getByTestId("canopus-offers");
  await expect(offers).toContainText("Not available: Nothing changed since the last investigation.");
  await offers.getByRole("button", { name: "Open Review & authorize" }).click();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Authorize action" })).toBeVisible();
  await page.keyboard.press("Escape");
  // An answer built from the records without model text is labelled as such.
  await box.fill("Show me the original message");
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByTestId("canopus-answer").nth(1)).toContainText(
    "Answer from the records · no model text",
  );
});

test("Canopus keeps its floating window but answers nothing while it has no backend", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto("/app/operations");
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const panel = page.locator(".canopus-window");
  await expect(panel).toBeVisible();
  // No case is open: there is nothing to ask about, and nothing is generated.
  await expect(panel).toContainText("Open a case to ask Canopus about it.");
  await expect(panel).toContainText("No case is open · nothing is generated here");
  await expect(panel.getByRole("textbox", { name: "Ask Canopus" })).toBeDisabled();
  await expect(panel.locator(".suggested-questions button")).toHaveCount(0);
  await expect(panel.locator("[data-role='assistant'], .message-assistant")).toHaveCount(0);
  // The window still expands and minimises as designed.
  await panel.getByRole("button", { name: "Expand conversation workspace" }).click();
  await expect(panel).toHaveAttribute("data-presentation", "expanded");
  await panel.getByRole("button", { name: "Minimize Canopus conversation" }).click();
  await expect(panel).toHaveAttribute("data-state", "closed");
});

test("Decisions, Audit, Explore and Settings read the backend", async ({ page }) => {
  await stubBackend(page);
  await page.goto("/app/decisions");
  await expect(page.locator(".decision-counts")).toContainText("1awaiting approval");
  const pending = page.getByTestId(`data-row-${CASE_A}`);
  await expect(pending).toContainText("Request depot reconciliation scan");
  await expect(pending).toContainText("Operator approval required");
  await page.getByRole("tab", { name: "Decision history" }).click();
  const history = page.locator("[data-testid^='data-row-']");
  await expect(history).toHaveCount(1);
  await expect(history.first()).toContainText("approved");
  await expect(history.first()).toContainText("Not stored by the backend yet");
  await expect(history.first()).toContainText("SYN-OPERATOR-LOCAL");

  await page.goto("/app/audit");
  await expect(page.getByTestId("audit-event-count")).toHaveText("4");
  const events = page.locator("[data-testid^='data-row-']");
  await expect(events).toHaveCount(4);
  await expect(events.first()).toContainText("Outcome verified");
  await expect(events.first()).toContainText("BACKEND");
  await expect(page.locator("body")).not.toContainText("SIMULATED");
  await events.first().getByRole("button", { name: "Outcome verified" }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "Suhail backend audit ledger · OUTCOME_VERIFIED",
  );
  await page.keyboard.press("Escape");

  await page.goto("/app/explore");
  await expect(page.getByTestId("explore-count")).toHaveText("3");
  await expect(page.getByTestId("network-map").locator(".shipment-cluster")).not.toHaveCount(0);
  await page.getByRole("tab", { name: "Schema" }).click();
  await expect(page.locator(".schema-entity")).toHaveCount(3);
  await page.locator(".schema-entity", { hasText: "Package" }).click();
  await expect(page.locator(".schema-inspector")).toContainText(
    "HAS_PACKAGE ← Shipment",
  );
  await expect(page.locator(".schema-view")).toContainText("Neo4j labels");

  await page.goto("/app/settings");
  await expect(page.locator("body")).toContainText("Backend connection");
  await expect(page.locator("body")).toContainText("shipments-v2-demo-live");
  await expect(page.locator("body")).toContainText("It is not SPL operational data");
  await expect(page.locator("body")).not.toContainText("Add a synthetic case");
  await expect(page.locator("body")).not.toContainText("Reset lab");
});

test("The clock control starts and pauses the backend's simulated clock, apart from Auto", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  await page.goto("/app/operations");
  const clock = page.getByTestId("clock-control");
  await expect(clock).toHaveText("Clock paused · Start");
  await clock.click();
  await expect(clock).toHaveText("Clock running ×60 · Pause");
  expect(stub.posts.at(-1)).toMatchObject({
    path: "/simulation/start",
    body: { speed: 60, replay_mode: "timeline" },
  });
  expect(stub.posts.at(-1)!.token).toBeTruthy();
  // Starting the clock does not start automatic investigation.
  await expect(page.getByRole("switch", { name: "Automatic investigation" })).not.toBeChecked();
  await clock.click();
  await expect(clock).toHaveText("Clock paused · Start");
  expect(stub.posts.map((post) => post.path)).toEqual(["/simulation/start", "/simulation/pause"]);
});

test("The Auto switch reflects the backend worker, and Arabic and dark mode still apply", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  await page.goto("/app/operations");
  const auto = page.getByRole("switch", { name: "Automatic investigation" });
  await expect(auto).not.toBeChecked();
  await auto.click();
  await expect(auto).toBeChecked();
  expect(stub.posts.map((post) => post.path)).toEqual(["/worker/start"]);
  await page.getByRole("button", { name: "Switch to Arabic" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(page.locator(".environment-badge")).toHaveText("متصل");
  await page.getByRole("button", { name: "تبديل المظهر" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
});

test("Connected screens for visual review", async ({ page }) => {
  // Captures the connected screens next to the lab's reference screenshots.
  await stubBackend(page);
  const shot = async (name: string) => {
    await page.waitForTimeout(900);
    await page.screenshot({ path: `screenshots/connected-${name}.png` });
  };
  await page.goto("/app/operations");
  await expect(page.locator("[data-testid^='data-row-']")).toHaveCount(2);
  await shot("operations");
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(
    page.getByTestId("knowledge-graph").locator(".entity-node").first(),
  ).toBeVisible();
  await shot("investigation");
  await page.goto("/app/decisions");
  await expect(page.getByTestId(`data-row-${CASE_A}`)).toContainText(
    "Request depot reconciliation scan",
  );
  await shot("decisions");
  await page.goto("/app/explore");
  await expect(page.getByTestId("explore-count")).toHaveText("3");
  await shot("explore");
  await page.goto("/app/audit");
  await expect(page.getByTestId("audit-event-count")).toHaveText("4");
  await shot("audit");
  await page.goto("/app/settings");
  await expect(page.locator("body")).toContainText("Backend connection");
  await shot("settings");
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  await expect(page.locator(".canopus-window")).toContainText(
    "Open a case to ask Canopus about it.",
  );
  await shot("canopus");
  await page.getByRole("button", { name: "Minimize Canopus conversation" }).click();

  // The same connected screens in Arabic, dark mode and at phone size.
  await page.goto(`/app/cases/${CASE_A}`);
  await page.getByRole("button", { name: "Switch to Arabic" }).click();
  await page.getByRole("button", { name: "تبديل المظهر" }).click();
  await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  await expect(
    page.getByTestId("knowledge-graph").locator(".entity-node").first(),
  ).toBeVisible();
  await shot("investigation-arabic-dark");
  await page.getByRole("button", { name: "Switch to English" }).click();
  await page.getByRole("button", { name: "Toggle theme" }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/app/operations");
  await expect(page.locator("[data-testid^='data-row-']")).toHaveCount(2);
  // No horizontal overflow of the page at phone width.
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await shot("operations-mobile");
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await expect(page.getByTestId("route-map")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await shot("investigation-mobile");
});
