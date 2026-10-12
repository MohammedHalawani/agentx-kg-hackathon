/**
 * Records one staged showcase video of Suhail from the real interface.
 *
 *   node recording/director.mjs --video A --map <evidence-map.json> [--base http://127.0.0.1:8022]
 *
 * What is real and what is staged (also in recording/README.md):
 *  - The case is a curated shipment in the synthetic world; the investigation, review, policy
 *    decision, simulated execution and verification run in the backend as they do for any case.
 *  - This script is the "director": it waits for each pipeline step to be reported by the
 *    backend (the rail's own state on the page) and only then plays that step's cue from the
 *    evidence map: which real graph records to light, which record to select so the map centres
 *    on it, and which workspace view to show. It invents no record and no step.
 *  - The phone (video A) is a picture of a simulated request, drawn by the page in director mode.
 *  - Clicks (Auto on, opening the case, approving when the policy asks, asking Canopus) are
 *    scripted. Waiting time is paced here and may be trimmed afterwards.
 */
import { chromium } from "playwright";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const VIDEO = arg("video", "A").toUpperCase();
const BASE = arg("base", "http://127.0.0.1:8022");
const MAP = JSON.parse(readFileSync(resolve(arg("map")), "utf-8"));
const OUT = resolve(arg("out", join(here, "out")));
const QUESTION = "What happened to this shipment, and how did Suhail resolve it?";
if (/:802[01]\b/.test(BASE)) throw new Error("the director runs on the staging backend only");
mkdirSync(OUT, { recursive: true });

const STEPS = ["Collect", "Graph", "Diagnose", "Precedent", "Recommend", "Review", "Disposition", "Outcome"];
/** How long each step's cue stays on screen (pacing only; the map may override with hold_ms). */
const HOLD = { Collect: 1600, Graph: 3600, Diagnose: 3000, Precedent: 1500, Recommend: 2400, Review: 2000, Disposition: 2200, Outcome: 4200 };
/** The evidence map's cue for a rail step: {highlight[], select, mode, fact}. */
const cueOf = (index) => (MAP.stages ?? []).find((item) => item.stage === STEPS[index]) ?? {};
const list = (value) => (value == null ? [] : Array.isArray(value) ? value : [value]);
const log = [];
let t0 = Date.now();
/** Stretches of the take that are only waiting, in seconds of video; finish.mjs removes them. */
const idle = [];
const waiting = async (promise) => {
  const from = (Date.now() - t0) / 1000;
  const value = await promise;
  const to = (Date.now() - t0) / 1000;
  if (to - from > 2) idle.push([+(from + 0.6).toFixed(2), +(to - 0.5).toFixed(2)]);
  return value;
};
const note = (text) => {
  const line = `+${((Date.now() - t0) / 1000).toFixed(1)}s ${text}`;
  log.push(line);
  console.log(line);
};
const api = async (path) => (await fetch(BASE + path)).json();
const token = async () => (await api("/operations/session")).token;
const post = async (path, body) =>
  fetch(BASE + path, {
    method: "POST",
    headers: { "X-Operations-Token": await token(), "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });

const browser = await chromium.launch({ channel: "chrome", args: ["--hide-scrollbars"] });
const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  deviceScaleFactor: 1,
  recordVideo: { dir: OUT, size: { width: 1920, height: 1080 } },
});
const page = await context.newPage();
t0 = Date.now(); // the video starts with the page
const pause = (ms) => page.waitForTimeout(ms);
const fire = (type, detail) =>
  page.evaluate(([name, data]) => window.dispatchEvent(new CustomEvent(name, { detail: data })), [type, detail]);
/** A visible, unhurried click: move, settle, press. */
async function click(locator) {
  const box = await locator.boundingBox();
  if (box) await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 18 });
  await pause(220);
  await locator.click();
}
const mode = async (name) => {
  const label = { balanced: "Balanced", map: "Map focus", graph: "Graph focus" }[name] ?? name;
  if (!label) return;
  const button = page.getByRole("button", { name: label, exact: true });
  if ((await button.getAttribute("aria-pressed")) !== "true") await click(button);
};
/** Wait until the backend has reported a step (the rail shows it running or done). */
const reached = (index, states = "running|completed|waiting|failed") =>
  page
    .locator(".pipeline-step")
    .nth(index)
    .and(page.locator(states.split("|").map((state) => `.state-${state}`).join(",")))
    .waitFor({ timeout: 6 * 60 * 1000 });

/** One step's cue: lit records, the selected record (which centres the map), the view. */
async function play(index, live = {}) {
  const cue = { ...cueOf(index), ...live };
  const modes = list(cue.mode);
  const selects = list(cue.select);
  const hold = cue.hold_ms ?? HOLD[STEPS[index]] ?? 2200;
  note(`cue ${STEPS[index]}: ${modes.join(" then ") || "keep view"}, ${cue.highlight?.length ?? 0} records, select ${selects.join(" then ") || "none"}`);
  // A step with two views (Diagnose: the place on the map, then the relationships) plays both.
  const beats = Math.max(modes.length, 1);
  for (let beat = 0; beat < beats; beat++) {
    if (modes[beat]) await mode(modes[beat]);
    const pick = selects[beat] ?? (beat === 0 ? selects[0] : undefined);
    if (pick) await fire("suhail:select", { id: pick });
    if (cue.highlight?.length)
      await fire("suhail:graph-highlight", { caseId: MAP.case_id, ids: cue.highlight });
    await pause(beats > 1 ? Math.round(hold * (beat === 0 ? 0.8 : 1.4)) : hold);
  }
  if (beats > 1) await mode("Balanced");
}

// ---- 0. Operations: sidebar open, Auto on, cases arriving ---------------------------------
await page.goto(`${BASE}/app/operations?director=1`);
await page.locator(".environment-badge[data-dataset=synthetic]").waitFor({ timeout: 90000 });
await pause(1800);
// Backstage: the simulated clock starts at the speed the fixture was prepared for.
await post("/simulation/start", { speed: Number(arg("speed", 60)), replay_mode: "timeline" });
await page.getByTestId("clock-control").filter({ hasText: /running/i }).waitFor({ timeout: 20000 });
await pause(900);
await click(page.getByRole("switch", { name: "Automatic investigation" }));
note("Auto on, clock running");
// The showcase case, as soon as the monitor has opened it.
const before = new Set(
  (await api("/cases/queue?scope=all&limit=100")).items.map((item) => item.case_id),
);
let caseId;
for (let tries = 0; !caseId && tries < 120; tries++) {
  const row = (await api("/cases/queue?scope=all&limit=100")).items.find(
    (item) => item.shipment_id === MAP.shipment_id && !before.has(item.case_id),
  );
  caseId = row?.case_id;
  if (!caseId) await pause(1500);
}
if (!caseId) throw new Error(`${MAP.shipment_id} did not open a case`);
MAP.case_id = caseId;
await waiting(page.getByTestId(`data-row-${caseId}`).waitFor({ timeout: 120000 }));
await pause(MAP.queue_hold_ms ?? 2600);
await click(page.getByTestId(`data-row-${caseId}`));
await page.getByRole("heading", { level: 1 }).waitFor();
await page.getByTestId("knowledge-graph").locator(".entity-node").first().waitFor({ timeout: 90000 });
note("case opened");

// ---- 1–6. The investigation, step by step as the backend reports it ------------------------
for (let index = 0; index <= 5; index++) {
  await waiting(reached(index));
  note(`${STEPS[index]} reported`);
  await play(index);
}
// ---- 7. Disposition -----------------------------------------------------------------------
await waiting(reached(6));
note("Disposition reported");
let detail = await api(`/cases/${caseId}`);
for (let tries = 0; /INVESTIGATING|RECOMMENDATION_READY/.test(detail.workflow_state) && tries < 90; tries++) {
  await pause(1000);
  detail = await api(`/cases/${caseId}`);
}
if (detail.recommendation?.approvable && !(detail.executions ?? []).length) {
  // The policy holds this action for a person: the operator's approval, as a visible click.
  await mode("balanced");
  await click(page.getByRole("button", { name: "Review & authorize" }));
  await pause(1500);
  await click(page.getByRole("dialog").getByRole("button", { name: "Authorize action" }));
  note("approved as the operator");
}
for (let tries = 0; !(detail.executions ?? []).length && tries < 90; tries++) {
  await pause(1000);
  detail = await api(`/cases/${caseId}`);
}
note(`execution ${detail.executions?.[0]?.status ?? "none"}`);
await play(6);
if (VIDEO === "A" && MAP.phone) {
  const { title, body, options, confirmation } = MAP.phone;
  const chosen = Math.max(0, typeof MAP.phone.chosen === "number" ? MAP.phone.chosen : options.indexOf(MAP.phone.chosen));
  await fire("suhail:phone", { step: 1, title: title.replace(/^Suhail\s*[—-]\s*/, ""), body, options, chosen, confirmation });
  await pause(3600);
  await fire("suhail:phone", { step: 2 });
  await pause(2600);
  await fire("suhail:phone", { step: 3 });
  await pause(1100);
  await fire("suhail:phone", { step: 4 });
  // Backstage, while the confirmation shows: simulated time moves so the staged scan arrives.
  const skipped = post("/simulation/skip", {}).then((response) => response.json().catch(() => ({})));
  await pause(2600);
  await fire("suhail:phone", { step: 0 });
  note(`skip: ${JSON.stringify(await skipped).slice(0, 160)}`);
} else {
  const skipped = await post("/simulation/skip", {}).then((response) => response.json().catch(() => ({})));
  note(`skip: ${JSON.stringify(skipped).slice(0, 160)}`);
}
// ---- 8. Outcome ---------------------------------------------------------------------------
for (let tries = 0; tries < 8; tries++) {
  detail = await api(`/cases/${caseId}`);
  if (detail.outcome || detail.workflow_state !== "AWAITING_OUTCOME") break;
  await post("/simulation/skip", {});
}
note(`outcome ${detail.outcome ? `${detail.outcome.verification_status} success ${detail.outcome.success}` : "none"}; state ${detail.workflow_state}`);
await page.locator(".pipeline-step").nth(7).and(page.locator(".state-completed, .state-waiting")).waitFor({ timeout: 120000 });
// The record that arrived in THIS take (its id differs from the reference run's).
const arrived = detail.outcome?.evidence_ids ?? [];
const outcomeCue = cueOf(7);
await play(7, arrived.length
  ? { select: arrived[0], highlight: [...(outcomeCue.highlight ?? []).filter((id) => !/-SIM-/.test(id)), ...arrived] }
  : {});
if (VIDEO === "B" && MAP.photo_node) {
  // The key moment: from the shipment to the stored proof photograph, enlarged, then back.
  await mode("graph");
  await fire("suhail:select", { id: MAP.photo_node });
  await pause(1800);
  await click(page.getByTestId("evidence-photo"));
  await pause(4200);
  await fire("suhail:select", { photo: false });
  await pause(700);
  await mode("balanced");
}
await pause(2600);

// ---- 9. Canopus, briefly ------------------------------------------------------------------
await click(page.getByRole("button", { name: "Open Canopus assistant" }));
const panel = page.locator(".canopus-window");
await click(panel.getByRole("button", { name: "Expand conversation workspace" }));
const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
await box.click();
await box.pressSequentially(QUESTION, { delay: 28 });
await pause(400);
await panel.getByRole("button", { name: "Send question" }).click();
note("question sent (the wait for the answer is trimmed afterwards)");
await waiting(panel.getByTestId("canopus-answer").waitFor({ timeout: 150000 }));
note(`answer: ${(await panel.getByTestId("canopus-answer").locator(".chat-prose").innerText()).replace(/\s+/g, " ")}`);
await pause(6500);
await click(panel.getByRole("button", { name: "Minimize Canopus conversation" }));
await pause(1400);
note("end of take");

// ---- Leave the backend as it should be: Auto off, clock paused ----------------------------
await post("/worker/pause");
await post("/simulation/pause");
const video = page.video();
await context.close();
await browser.close();
const raw = await video.path();
const target = join(OUT, `suhail-video-${VIDEO}-raw.webm`);
renameSync(raw, target);
writeFileSync(join(OUT, `suhail-video-${VIDEO}-timeline.txt`), `${log.join("\n")}\n`);
console.log(`recorded ${target}`);
