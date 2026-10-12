/**
 * Checks every control and cue the director uses, on the prepared world, WITHOUT starting the
 * clock or Auto and without asking the model: it spends nothing. Run it before a take.
 *
 *   node recording/rehearse.mjs --map <evidence-map.json> [--base http://127.0.0.1:8022]
 */
import { chromium } from "playwright";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const arg = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const BASE = arg("base", "http://127.0.0.1:8022");
const MAP = JSON.parse(readFileSync(resolve(arg("map")), "utf-8"));
const browser = await chromium.launch({ channel: "chrome" });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
// Recording mode for every page of this browser, whichever page loads first.
await context.addInitScript(() => window.sessionStorage.setItem("suhail-director", "1"));
const page = await context.newPage();
const fire = (type, detail) =>
  page.evaluate(([name, data]) => window.dispatchEvent(new CustomEvent(name, { detail: data })), [type, detail]);
const results = [];
const check = async (name, run) => {
  try {
    await run();
    results.push(`ok    ${name}`);
  } catch (error) {
    results.push(`FAIL  ${name}: ${String(error.message).split("\n")[0]}`);
  }
};
const visible = (locator) => locator.waitFor({ timeout: 8000 });

await page.goto(`${BASE}/app/operations?director=1`);
await check("operations page", () => visible(page.locator(".environment-badge[data-dataset=synthetic]")));
await check("sidebar open with the logo", () => visible(page.locator("img[src*='suhail-logo']")));
await check("clock control says paused", () => visible(page.getByTestId("clock-control").filter({ hasText: /paused/i })));
await check("Auto switch is off", async () => {
  const state = await page.getByRole("switch", { name: "Automatic investigation" }).getAttribute("aria-checked");
  if (state !== "false") throw new Error(`aria-checked is ${state}`);
});
const queue = await (await fetch(`${BASE}/cases/queue?scope=all&limit=100`)).json();
const row = queue.items[0];
await check(`queue row ${row?.shipment_id}`, () => visible(page.getByTestId(`data-row-${row.case_id}`)));
await page.getByTestId(`data-row-${row.case_id}`).click();
await check("case page", () => visible(page.getByRole("heading", { level: 1 })));
await check("graph drawn", () => visible(page.getByTestId("knowledge-graph").locator(".entity-node").first()));
await check("eight pipeline steps", async () => {
  const count = await page.locator(".pipeline-step").count();
  if (count !== 8) throw new Error(`${count} steps`);
});
await check("steps carry the backend's own state for pacing", async () => {
  const count = await page.locator(".pipeline-step[data-reported]").count();
  if (count !== 8) throw new Error(`${count} steps marked`);
});
await check("the rail can be held back and released", async () => {
  await fire("suhail:rail", { cap: 2 });
  await page.locator(".pipeline-step").nth(3).and(page.locator(".state-queued")).waitFor({ timeout: 4000 });
  await fire("suhail:rail", { cap: null });
  await page.waitForTimeout(300);
});
await check("a finished step carries a state", () => visible(page.locator(".pipeline-step").first().and(page.locator(".state-completed, .state-waiting, .state-failed"))));
for (const name of ["Map focus", "Graph focus", "Balanced view"])
  await check(`view button ${name}`, async () => {
    await page.getByRole("button", { name, exact: true }).click();
    await page.waitForTimeout(500);
  });
const detail = await (await fetch(`${BASE}/cases/${row.case_id}`)).json();
const some = detail.evidence.nodes.slice(0, 4).map((node) => node.id);
await check("select a record", async () => {
  await fire("suhail:select", { id: some[0] });
  await page.waitForTimeout(600);
});
await check("light records", () => fire("suhail:graph-highlight", { caseId: row.case_id, ids: some }));
await check("phone in", async () => {
  await fire("suhail:phone", { step: 1, title: "t", body: "b", options: MAP.phone?.options ?? ["a"], chosen: 0, confirmation: "c" });
  await visible(page.locator(".director-phone.in"));
  await fire("suhail:phone", { step: 4 });
  await visible(page.locator(".phone-confirmed"));
});
await check("phone out", async () => {
  await fire("suhail:phone", { step: 0 });
  await page.locator(".director-phone").waitFor({ state: "detached", timeout: 5000 });
});
await check("Canopus opens", () => page.getByRole("button", { name: "Open Canopus assistant" }).click());
const panel = page.locator(".canopus-window");
await check("Canopus expands", () => panel.getByRole("button", { name: "Expand conversation workspace" }).click());
await check("Canopus question box", () => visible(panel.getByRole("textbox", { name: "Ask Canopus about this case" })));
await check("Canopus send button", () => visible(panel.getByRole("button", { name: "Send question" })));
await check("Canopus minimizes", () => panel.getByRole("button", { name: "Minimize Canopus conversation" }).click());
await check("approval control (only if this case is approvable)", async () => {
  if (detail.recommendation?.approvable) await visible(page.getByRole("button", { name: "Review & authorize" }));
});
const status = await (await fetch(`${BASE}/worker/status`)).json();
results.push(`world: worker ${status.worker.state}, clock ${status.simulator.state}, ${status.as_of}`);
await browser.close();
console.log(results.join("\n"));
process.exit(results.some((line) => line.startsWith("FAIL")) ? 1 : 0);
