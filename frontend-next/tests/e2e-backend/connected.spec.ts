import { existsSync, readFileSync } from "node:fs";
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
  await expect(map.locator(".evidence-marker.vehicle_only")).toHaveCount(9);
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

test("A case reads as one assessment with a connected pipeline; details and commentary are optional", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  // The backend's brief and stage facts, in the contract's shape.
  stub.state.detailA = {
    ...stub.state.detailA,
    brief: {
      resolved: false,
      waiting_kind: "awaiting_new_evidence",
      waiting_label_en: "Waiting for new evidence",
      lines: [
        { key: "problem", label_en: "Problem", text_en: "Barcode mismatch detected at the sorting center." },
        { key: "finding", label_en: "Finding", text_en: "One scanner recorded a barcode inconsistent with the manifest." },
        { key: "action", label_en: "Action taken", text_en: "Rescan request sent to sorter SYN-DEV-SR-SORT-JED-01 (simulated). If nothing arrives by 18 Sept, the case goes to a person." },
        { key: "status", label_en: "Current status", text_en: "Waiting for the new scan to verify the mismatch is corrected." },
      ],
      suspected_cause: { status: "accepted", text_en: "Suhail's investigation concluded a barcode mismatch.", confidence: "medium" },
      evidence: [{ id: `${SHIP_A}-CUST-02-01`, label_en: "Custody record at the Dammam depot", in_graph: true }],
      review: { status: "accepted", text_en: "The independent review accepted the finding.", reason_original: "Citations are valid." },
      policy: { decision: "automatic", text_en: "A rescan is allowed automatically.", rule_id: "AUTH-10-auto-allowlist" },
      actions: [
        {
          action_type: "REQUEST_RESCAN",
          status: "sent",
          simulated: true,
          text_en: "Rescan request sent to sorter SYN-DEV-SR-SORT-JED-01 (simulated). Suhail is waiting for a new barcode read of this parcel.",
          deadline_text_en: "If no such record arrives by 18 Sept, the verifier records the action as not confirmed and the case goes to a person.",
          outcome: null,
        },
      ],
      technical: { workflow_state: "AWAITING_OUTCOME", authority_rule_id: "AUTH-10-auto-allowlist" },
    },
    pipeline: {
      ...stub.state.detailA.pipeline!,
      stage_facts: [
        { stage: "extract", status: "done", fact_en: "Case opened for: barcode read differs", sequence: 1 },
        { stage: "classify", status: "done", fact_en: "Suspected cause: barcode mismatch", sequence: 3 },
      ],
    },
  };
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  // One assessment: the four lines, in the backend's words.
  const assessment = page.getByTestId("case-assessment");
  await expect(assessment).toContainText("Barcode mismatch detected at the sorting center.");
  await expect(assessment).toContainText("Rescan request sent to sorter");
  await expect(assessment).toContainText("Waiting for new evidence");
  // The pending action says who received the request, what is awaited and until when.
  const pending = page.getByTestId("pending-action");
  await expect(pending).toContainText("sent to sorter SYN-DEV-SR-SORT-JED-01 (simulated)");
  await expect(pending).toContainText("the case goes to a person");
  // Rule ids and the reviewer's own words only in the details.
  await expect(assessment).not.toContainText("AUTH-10-auto-allowlist");
  await assessment.getByRole("button", { name: "Evidence and technical details" }).click();
  await expect(assessment).toContainText("AUTH-10-auto-allowlist");
  await expect(assessment).toContainText("Citations are valid.");
  // The pipeline is one connected line with the backend's short fact under a step.
  await expect(page.locator(".pipeline-stages.connected")).toBeVisible();
  await expect(page.getByTestId("stage-explain-2")).toHaveText("Suspected cause: barcode mismatch");
  // The sidebar folds to give the case room; the logo becomes the star.
  await expect(page.locator(".suhail-sidebar [data-state='collapsed'], [data-state='collapsed'].suhail-sidebar, [data-slot='sidebar'][data-state='collapsed']").first()).toBeAttached();
  // Nothing to inspect yet: one quiet line.
  await expect(page.getByTestId("evidence-inspector")).toHaveClass(/idle/);
  await page.screenshot({ path: "screenshots/graph/calm-case.png", fullPage: true });
});

// The backend's own example briefs (real archived runs), rendered for review when present.
for (const name of [
  "brief_000375_awaiting_evidence",
  "brief_000375_resolved",
  "brief_000232_review_rejected",
  "brief_000058_action_not_confirmed",
]) {
  const file = `C:/Projects/demo/.stage4/docs/api/examples/${name}.json`;
  test(`The backend's example ${name} renders as one assessment`, async ({ page }) => {
    test.skip(!existsSync(file), "the backend's example file is not on this machine");
    const example = JSON.parse(readFileSync(file, "utf-8"));
    const stub = await stubBackend(page);
    stub.state.detailA = {
      ...stub.state.detailA,
      brief: example.brief,
      next_step: example.brief.next_step,
      pipeline: { ...stub.state.detailA.pipeline!, stage_facts: example.stage_facts },
    };
    await page.goto(`/app/cases/${CASE_A}`);
    const assessment = page.getByTestId("case-assessment");
    for (const line of example.brief.lines as { text_en: string }[])
      await expect(assessment).toContainText(line.text_en);
    // A round the reviewer sent back is a review outcome, never a failed step.
    await expect(page.locator(".pipeline-step.state-failed")).toHaveCount(0);
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `screenshots/graph/calm-${name}.png`, fullPage: true });
  });
}

test("Recording hooks exist only in director mode; a stored photograph opens from its record", async ({
  page,
}) => {
  const stub = await stubBackend(page);
  const phone = {
    step: 1,
    title: "Custody confirmation required",
    body: "Your route has ended, but shipment SH-001 has no delivery confirmation or warehouse return scan. Please confirm its status.",
    options: ["Scan package into warehouse", "Provide delivery confirmation", "Report package missing"],
    chosen: 0,
    confirmation: "Warehouse scan recorded",
  };
  const cue = (type: string, detail: unknown) =>
    page.evaluate(
      ([name, data]) => window.dispatchEvent(new CustomEvent(name as string, { detail: data })),
      [type, detail],
    );
  // The normal product: the cue does nothing and nothing of the phone exists.
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await cue("suhail:phone", phone);
  await page.waitForTimeout(400);
  await expect(page.locator(".director-phone")).toHaveCount(0);
  // A record that carries a stored image shows it, and it enlarges on click.
  const pixel = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
    "base64",
  );
  await page.route("**/media/proof.png", (route) =>
    route.fulfill({ status: 200, contentType: "image/png", body: pixel }),
  );
  const custody = `${SHIP_A}-CUST-02-01`;
  stub.state.detailA = {
    ...stub.state.detailA,
    evidence: {
      ...stub.state.detailA.evidence,
      nodes: stub.state.detailA.evidence.nodes.map((node) =>
        node.id === custody
          ? { ...node, properties: { ...node.properties, media_url: "/media/proof.png" } }
          : node,
      ),
    },
  };
  // Director mode, for the recording script only.
  await page.goto(`/app/cases/${CASE_A}?director=1`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await expect(page.getByTestId("knowledge-graph").locator(".entity-node").first()).toBeVisible();
  await cue("suhail:select", { id: custody });
  await page.getByTestId("evidence-photo").click();
  await expect(page.getByTestId("photo-modal").locator("img")).toHaveAttribute(
    "src",
    "/media/proof.png",
  );
  await cue("suhail:select", { photo: false });
  await expect(page.getByTestId("photo-modal")).toHaveCount(0);
  await cue("suhail:phone", phone);
  const overlay = page.locator(".director-phone");
  await expect(overlay).toHaveClass(/in/);
  await expect(overlay).toContainText("Custody confirmation required");
  await page.waitForTimeout(1500);
  await page.screenshot({ path: "screenshots/graph/phone-1.png" });
  await cue("suhail:phone", { step: 2 });
  await expect(overlay).toContainText("Provide delivery confirmation");
  await cue("suhail:phone", { step: 3 });
  await page.waitForTimeout(700);
  await page.screenshot({ path: "screenshots/graph/phone-3.png" });
  await cue("suhail:phone", { step: 4 });
  await expect(overlay).toContainText("Warehouse scan recorded");
  await page.waitForTimeout(700);
  await page.screenshot({ path: "screenshots/graph/phone-4.png" });
  await cue("suhail:phone", { step: 0 });
  await expect(overlay).toHaveCount(0, { timeout: 5000 });
  // It asked the backend for nothing: the phone is a picture, not a request.
  expect(stub.posts).toHaveLength(0);
});

test("Canopus is a plain chat about the open case: answers first, sources and agent quotes on request", async ({
  page,
}) => {
  await stubBackend(page);
  await page.goto(`/app/cases/${CASE_A}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(SHIP_A);
  await page.getByRole("button", { name: "Open Canopus assistant" }).click();
  const panel = page.locator(".canopus-window");
  await expect(panel).toContainText("It takes no action on its own.");
  // No automatic cards: no narration, no markers, nothing until a question is asked.
  await expect(panel.getByTestId("narration-bubble")).toHaveCount(0);
  await expect(panel.getByTestId("canopus-answer")).toHaveCount(0);
  const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
  await box.fill("What happened to this shipment?");
  await panel.getByRole("button", { name: "Send question" }).click();
  // The operator's message on one side, a readable answer on the other.
  await expect(panel.locator(".chat-question")).toHaveText("What happened to this shipment?");
  const answer = panel.getByTestId("canopus-answer");
  await expect(answer.locator(".chat-prose")).toHaveText(
    "The reviewer accepted the finding; the action waits for an operator.",
  );
  // No quote, record id, rule id or refused action in the conversation by default.
  await expect(answer.getByTestId("canopus-quote")).toHaveCount(0);
  await expect(answer).not.toContainText("AUTH-");
  await expect(answer).not.toContainText("Not available");
  await expect(answer).not.toContainText(`${SHIP_A}-CUST-02-01`);
  // Only the action the rules allow now, and it opens the existing dialog.
  const offers = answer.getByTestId("canopus-offers");
  await expect(offers.getByRole("button")).toHaveCount(1);
  // Sources are secondary: the agent's recorded words and the record ids, one click away.
  await answer.getByRole("button", { name: "Sources" }).click();
  const sources = answer.getByTestId("canopus-sources");
  await expect(sources.getByTestId("canopus-quote")).toContainText(
    "Citations are valid and support the conclusion.",
  );
  await expect(sources).toContainText(`${SHIP_A}-CUST-02-01`);
  await offers.getByRole("button", { name: /review and authorize/ }).click();
  await expect(
    page.getByRole("dialog").getByRole("button", { name: "Authorize action" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  // Asked for the original message: it is quoted in the answer, labelled with its source.
  await box.fill("Show me the reviewer's original message");
  await panel.getByRole("button", { name: "Send question" }).click();
  const second = panel.getByTestId("canopus-answer").nth(1);
  await expect(second.getByTestId("canopus-quote")).toContainText("The reviewer's own words");
  await expect(second).toContainText("from the case record");
  // Asked why something cannot be done: the reason in plain words, without a rule id.
  await box.fill("Why can't you re-analyse the case?");
  await panel.getByRole("button", { name: "Send question" }).click();
  const third = panel.getByTestId("canopus-answer").nth(2);
  await expect(third.getByTestId("canopus-unavailable")).toContainText(
    "Nothing changed since the last investigation.",
  );
  await expect(third.getByTestId("canopus-unavailable")).not.toContainText("AUTH-24");
  await page.screenshot({ path: "screenshots/graph/calm-chat.png" });
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
  // Skip to the next event: one call, then one plain line of what the backend reports.
  await page.getByTestId("clock-skip").click();
  await expect(page.locator("[data-sonner-toast]")).toContainText(
    `Skipped 9 hours: a new case opened, ${SHIP_A}.`,
  );
  expect(stub.posts.at(-1)!.path).toBe("/simulation/skip");
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
