// Read-only browser walkthrough of the running V3 app: navigation and inspection only, no control is pressed
// that changes a case. Every request the pages make is recorded; any that is not a GET is reported.
const { chromium } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const BASE = process.env.V3_BASE || "http://127.0.0.1:8023";
const OUT = process.env.V3_OUT || "C:\\Projects\\suhail-v3-integration\\artifacts\\v3\\walkthrough";

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const requests = [];
  const consoleErrors = [];
  page.on("request", (r) => requests.push({ method: r.method(), url: r.url().replace(BASE, "") }));
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text().slice(0, 200)));
  const report = { base: BASE, started: new Date().toISOString(), pages: [], cases: [] };
  const shot = async (name, full = true) => {
    const file = path.join(OUT, name + ".png");
    await page.screenshot({ path: file, fullPage: full });
    return file;
  };

  const queue = await (await page.request.get(BASE + "/cases/queue?scope=all&limit=100")).json();
  await page.goto(BASE + "/app/operations");
  await page.getByRole("link", { name: /Open investigation for/ }).first().waitFor({ timeout: 60000 });
  const rows = await page.getByRole("link", { name: /Open investigation for/ }).allInnerTexts();
  const body = await page.locator("main").innerText();
  report.pages.push({ page: "operations", rows: rows.length, shipments: rows.map((r) => r.split("\n")[0]),
    control_shipment_listed: /SYN-SHP-000051/.test(body), auto: /Auto\s*\n\s*Paused/.test(body),
    active_panel: await page.getByTestId("active-investigations").count(), screenshot: await shot("01-operations") });

  let index = 2;
  for (const row of queue.items) {
    const sid = row.shipment_id;
    await page.goto(`${BASE}/app/cases/${row.case_id}`);
    await page.locator(".leaflet-marker-icon").first().waitFor({ timeout: 60000 });
    await page.getByText(/graph draws from/).waitFor({ timeout: 30000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const main = await page.locator("main").innerText();
    const entry = {
      shipment_id: sid, case_id: row.case_id,
      header_status: (main.match(/\n(Queued|Investigating|Needs evidence|Human review|Awaiting approval|Resolved)\n/) || [])[1] || null,
      graph_caption: (main.match(/graph draws from[^\n]*/) || [])[0] || null,
      assessment: (main.match(/CASE ASSESSMENT\n([^\n]*)/) || [])[1] || null,
      finding: (main.match(/FINDING\n([^\n]*)/) || [])[1] || null,
      action_taken: (main.match(/ACTION TAKEN\n([^\n]*)/) || [])[1] || null,
      map_markers: await page.locator(".leaflet-marker-icon").count(),
      map_paths: await page.locator(".leaflet-overlay-pane path").count(),
      map_legend: ["Confirmed custody", "Expected route", "Vehicle only"].filter((label) => main.includes(label)),
      gps_disclaimer: main.includes("Vehicle GPS proves vehicle movement, not parcel custody."),
      chronology_present: await page.getByTestId("evidence-chronology").count(),
      says_delivered: /\bdelivered\b/i.test(main), says_traffic: /traffic/i.test(main),
      screenshots: [await shot(`${String(index).padStart(2, "0")}-${sid}-case`)],
    };
    // Inspect one vehicle observation from the map (inspection only).
    const vehicle = page.locator(".leaflet-marker-icon", { hasText: "↗" }).first();
    if (await vehicle.count()) {
      await vehicle.click({ force: true }).catch(() => {});
      await page.waitForTimeout(800);
      const after = await page.locator("main").innerText();
      entry.vehicle_marker = { telemetry_only_label: /Vehicle telemetry only/i.test(after),
        graph_node_selected: await page.locator(".entity-node.evidence-selected").count(),
        inspector: (after.match(/Vehicle (position|telemetry)[^\n]*(\n[^\n]*){0,6}/i) || [""])[0].slice(0, 400) };
      entry.screenshots.push(await shot(`${String(index).padStart(2, "0")}-${sid}-vehicle-observation`, false));
    }
    // The whole bounded graph.
    const all = page.getByText(/^All \d+ records$/).first();
    if (await all.count()) {
      await all.click().catch(() => {});
      await page.waitForTimeout(1500);
      entry.graph_nodes_drawn = await page.locator(".entity-node").count();
      const graph = page.locator(".react-flow, .knowledge-graph").first();
      if (await graph.count()) await graph.scrollIntoViewIfNeeded().catch(() => {});
      entry.screenshots.push(await shot(`${String(index).padStart(2, "0")}-${sid}-graph`, false));
    }
    report.cases.push(entry);
    index += 1;
  }

  // The ordinary control shipment: present as a shipment, never as an investigation case.
  await page.goto(BASE + "/app/explore");
  await page.waitForTimeout(4000);
  const explore = await page.locator("main").innerText();
  report.pages.push({ page: "explore", lists_control_shipment: /SYN-SHP-000051/.test(explore), screenshot: await shot("90-explore") });
  await page.goto(BASE + "/app/cases/SYN-SHP-000051");
  await page.waitForTimeout(4000);
  const control = await page.locator("main").innerText();
  report.pages.push({ page: "control shipment by id", text: control.slice(0, 700), screenshot: await shot("91-control-shipment") });
  await page.goto(BASE + "/app/audit");
  await page.waitForTimeout(3000);
  report.pages.push({ page: "audit", text_head: (await page.locator("main").innerText()).slice(0, 300), screenshot: await shot("92-audit") });

  report.requests_total = requests.length;
  report.non_get_requests = requests.filter((r) => r.method !== "GET");
  report.request_paths = [...new Set(requests.map((r) => r.method + " " + r.url.replace(/SYN-[A-Za-z0-9-]+/g, "{id}").replace(/\?.*$/, "")))].filter((p) => !p.includes("/app/assets")).sort();
  report.console_errors = consoleErrors;
  report.finished = new Date().toISOString();
  fs.writeFileSync(path.join(OUT, "walkthrough.json"), JSON.stringify(report, null, 1));
  await browser.close();
  console.log(JSON.stringify({ cases: report.cases.length, non_get: report.non_get_requests.length, console_errors: consoleErrors.length, out: OUT }));
})().catch((error) => { console.error(error); process.exit(1); });
