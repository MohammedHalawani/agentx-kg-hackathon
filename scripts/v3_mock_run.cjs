// Two active cases and stale-run protection on the MOCK-provider backend (disposable database only).
// The Auto switch of the real frontend is pressed; everything else is read through the HTTP surface.
const { chromium } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const BASE = "http://127.0.0.1:8024";
const TARGET = "shipments-v2-world-v3-ci-20261013";
const OUT = "C:\\Projects\\suhail-v3-integration\\artifacts\\v3\\mock-two-cases";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const posts = [];
  context.on("request", (r) => r.method() !== "GET" && posts.push({ at: new Date().toISOString(), method: r.method(), path: r.url().replace(BASE, "") }));
  const api = async (p) => (await context.request.get(BASE + p)).json();
  const shot = async (target, name, full = true) => { const file = path.join(OUT, name + ".png"); await target.screenshot({ path: file, fullPage: full }); return file; };
  const until = async (label, check, seconds) => {
    const end = Date.now() + seconds * 1000;
    for (;;) { const value = await check(); if (value) return value; if (Date.now() > end) throw new Error("timed out: " + label); await sleep(500); }
  };
  const brief = (s) => ({ case_id: s.case_id, shipment_id: s.shipment_id, worker_id: s.worker_id, claim_epoch: s.claim_epoch, run_id: s.run_id,
    run_status: s.run_status, workflow_state: s.workflow_state, active_stage: s.active_stage, lease: Boolean(s.lease_expires_at), final_result: s.final_result });
  const report = { base: BASE, started: new Date().toISOString(), steps: {} };

  const status0 = await api("/worker/status");
  if (status0.database !== TARGET) throw new Error("not the disposable database: " + status0.database);
  report.setup = { database: status0.database, worker: status0.worker.state, concurrency: status0.worker.concurrency,
    cases_opened: status0.session.monitor_opened, provider: await api("/__mock/provider") };

  await page.goto(BASE + "/app/operations");
  await page.getByRole("link", { name: /Open investigation for/ }).first().waitFor({ timeout: 90000 });
  const auto = page.getByRole("switch", { name: "Automatic investigation" });
  report.steps.before = { auto_checked: await auto.isChecked(), rows: await page.getByRole("link", { name: /Open investigation for/ }).count(),
    screenshot: await shot(page, "m01-operations-before") };

  // 1. Auto on: two workers claim two different cases.
  await auto.click();
  const two = await until("two active cases", async () => { const s = await api("/worker/status"); return s.worker.active_count === 2 ? s : null; }, 60);
  const first = two.worker.active_cases.map(brief);
  await page.getByTestId("active-investigations").waitFor({ timeout: 30000 });
  await page.getByText("2 active investigations").waitFor({ timeout: 30000 });
  report.steps.two_active = { wire: { concurrency: two.worker.concurrency, active_count: two.worker.active_count, active_case_id: two.worker.active_case_id,
      active_cases: first }, ui_cards: await page.getByTestId("active-investigations").getByRole("link").count(),
    ui_text: (await page.getByTestId("active-investigations").innerText()).replace(/\n+/g, " | "),
    provider: await api("/__mock/provider"), screenshot: await shot(page, "m02-two-active-investigations") };
  const casePage = await context.newPage();
  await casePage.goto(`${BASE}/app/cases/${first[0].case_id}`);
  await casePage.locator('section[aria-label="Investigation pipeline"]').waitFor({ timeout: 30000 });
  await sleep(2500);
  const pipelineText = async () => (await casePage.locator('section[aria-label="Investigation pipeline"]').innerText()).replace(/\n+/g, " | ").slice(0, 400);
  report.steps.case_running = { case_id: first[0].case_id, pipeline: await pipelineText(), screenshot: await shot(casePage, "m03-case-while-running", false) };

  // 2. Pause while both are in flight: both claims are revoked; what their workers still return must be refused.
  await page.bringToFront();
  await auto.click();
  await until("claims revoked", async () => (await api("/worker/status")).worker.active_count === 0, 30);
  const revokedAt = new Date().toISOString();
  await until("mock calls drained", async () => (await api("/__mock/provider")).in_flight === 0, 60);
  await sleep(4000);                                  // the late answers have come back by now
  const afterPause = [];
  for (const claim of first) {
    const detail = await api(`/cases/${claim.case_id}`);
    const audit = await api(`/audit?case_id=${claim.case_id}&limit=100`);
    afterPause.push({ ...brief(detail.investigation_status), old_run_id: claim.run_id,
      diagnosis_available: detail.diagnosis?.available ?? null, recommendation: detail.recommendation ? "present" : null,
      review: detail.review ? "present" : null, executions: (detail.executions ?? []).length,
      previous_run_status: detail.previous_run?.status ?? detail.run?.status ?? null,
      audit_events: (audit.items ?? []).map((a) => a.event_type) });
  }
  await sleep(1500);
  report.steps.after_pause = { revoked_at: revokedAt, cases: afterPause, case_page_pipeline: await pipelineText(),
    case_page_header: ((await casePage.locator("main").innerText()).match(/\n(Queued|Investigating|Needs evidence|Human review|Awaiting approval)\n/) || [])[1] || null,
    provider: await api("/__mock/provider"), screenshots: [await shot(casePage, "m04-case-after-pause", false), await shot(page, "m05-operations-after-pause")] };

  // 3. Resume: new claims, new runs, higher epochs; the cases finish from the new runs only.
  await auto.click();
  const done = await until("both first cases finished", async () => {
    const details = await Promise.all(first.map((c) => api(`/cases/${c.case_id}`)));
    return details.every((d) => d.investigation_status.run_status === "REVIEWED") ? details : null;
  }, 240);
  await auto.click();                                 // stop taking more cases
  await until("idle", async () => (await api("/worker/status")).worker.active_count === 0, 30);
  await until("mock calls drained", async () => (await api("/__mock/provider")).in_flight === 0, 60);
  await sleep(2000);
  const finished = done.map((d, i) => ({ ...brief(d.investigation_status), old_run_id: first[i].run_id, old_epoch: first[i].claim_epoch,
    new_run: d.investigation_status.run_id !== first[i].run_id, epoch_advanced: d.investigation_status.claim_epoch > first[i].claim_epoch,
    review_verdict: d.review?.verdict ?? null, model: d.run?.result?.model ?? d.diagnosis?.model ?? null,
    diagnosis_available: d.diagnosis?.available ?? null, executions: (d.executions ?? []).length, outcome: d.outcome ? "present" : null }));
  await casePage.reload();
  await casePage.locator('section[aria-label="Investigation pipeline"]').waitFor({ timeout: 30000 });
  await sleep(3000);
  const caseMain = await casePage.locator("main").innerText();
  report.steps.finished = { cases: finished, case_page_pipeline: await pipelineText(),
    case_page_mentions_mock: /MOCK PROVIDER/.test(caseMain), case_page_says_verified: /verified outcome|Resolved\n/i.test(caseMain) && !/not verified/i.test(caseMain),
    screenshots: [await shot(casePage, "m06-case-finished-from-new-run"), await shot(page, "m07-operations-after")] };
  const last = await api("/worker/status");
  report.final = { worker: { state: last.worker.state, active_count: last.worker.active_count, processed_count: last.worker.processed_count },
    provider: await api("/__mock/provider"), ui_posts: posts };
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, "mock-run.json"), JSON.stringify(report, null, 1));
  await browser.close();
  console.log(JSON.stringify({ ok: true, peak: report.final.provider.peak_in_flight, calls: report.final.provider.calls, out: OUT }));
})().catch((error) => { console.error(String(error && error.stack || error)); process.exit(1); });
