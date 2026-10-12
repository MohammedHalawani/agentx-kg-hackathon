/**
 * Records one staged showcase video of Suhail from the real interface.
 *
 *   node recording/director.mjs --video A --map <evidence-map.json> [--base http://127.0.0.1:8022]
 *   node recording/director.mjs --video B --map <evidence-map.json> [--first-map "<command>"]
 *   node recording/director.mjs --video B --map <...> --case <case id> --tail   (rehearsal, writes nothing)
 *
 * What is real and what is staged (also in recording/README.md):
 *  - The case is a curated shipment in the synthetic world; the investigation, review, policy
 *    decision, simulated execution and verification run in the backend as they do for any case.
 *  - This script is the "director". It moves a pointer and clicks like a person would. It lets
 *    the pipeline rail show one more finished step only after the backend has reported that
 *    step, and holds each step long enough to read; the rail is never ahead of the backend.
 *    With each step it lights real graph records from the evidence map.
 *  - The phone (video A) is a picture of a simulated request, drawn by the page in recording mode.
 *  - Simulated time is started and moved forward off screen. Waiting is marked and removed
 *    afterwards by finish.mjs; nothing is reordered or sped up. No text is added to the picture.
 */
import { chromium } from "playwright";
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const flag = (name) => process.argv.includes(`--${name}`);
const VIDEO = arg("video", "A").toUpperCase();
const BASE = arg("base", "http://127.0.0.1:8022");
const MAP = JSON.parse(readFileSync(resolve(arg("map")), "utf-8"));
const OUT = resolve(arg("out", join(here, "out")));
const TAIL = flag("tail"); // rehearsal of the closing part on an existing case; records nothing in the backend
const QUESTION =
  arg("ask") ??
  (VIDEO === "A"
    ? "What happened here, and how was it resolved?"
    : "What changed, and what still needs a person?");
if (/:802[01]\b/.test(BASE)) throw new Error("the director runs on the staging backend only");
mkdirSync(OUT, { recursive: true });

const STEPS = ["Collect", "Graph", "Diagnose", "Precedent", "Recommend", "Review", "Disposition", "Outcome"];
/** How long each step stays on screen once it is shown as finished (reading pace). */
const BEAT = { Collect: 1900, Graph: 2000, Diagnose: 2000, Precedent: 1900, Recommend: 2000, Review: 1900, Disposition: 1500, Outcome: 2400 };
const cueOf = (index) => (MAP.stages ?? []).find((item) => item.stage === STEPS[index]) ?? {};
const list = (value) => (value == null ? [] : Array.isArray(value) ? value : [value]);
const log = [];
let t0 = Date.now();
const now = () => (Date.now() - t0) / 1000;
const note = (text) => {
  const line = `+${now().toFixed(1)}s ${text}`;
  log.push(line);
  console.log(line);
};
/** Stretches of the take that are only waiting, in seconds of video; finish.mjs removes them. */
const idle = [];
const waiting = async (promise, keep = 0.4) => {
  const from = now();
  const value = await promise;
  const to = now();
  if (to - from > keep + 1.2) idle.push([+(from + keep).toFixed(2), +(to - 0.4).toFixed(2)]);
  return value;
};
/** A read from the backend; a dropped connection is tried again. */
const api = async (path) => {
  for (let tries = 0; ; tries++)
    try {
      return await (await fetch(BASE + path)).json();
    } catch (error) {
      if (tries >= 4) throw error;
      await new Promise((done) => setTimeout(done, 800));
    }
};
const token = async () => (await api("/operations/session")).token;
const post = async (path, body) => {
  const headers = { "X-Operations-Token": await token(), "Content-Type": "application/json" };
  try {
    return await fetch(BASE + path, { method: "POST", headers, body: body ? JSON.stringify(body) : undefined });
  } catch (error) {
    // A dropped connection reads as a refusal; the callers ask again.
    return new Response(JSON.stringify({ detail: String(error.message) }), { status: 599 });
  }
};

const browser = await chromium.launch({ channel: "chrome", args: ["--hide-scrollbars"] });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
// Recording mode for every page of this browser; the rail is paced unless this is a rehearsal.
await context.addInitScript((paced) => {
  window.sessionStorage.setItem("suhail-director", "1");
  if (paced) window.sessionStorage.setItem("suhail-director-rail", "paced");
  // The pointer: the page draws an arrow where the mouse is, for the recording only.
  window.addEventListener("DOMContentLoaded", () => {
    const arrow = document.createElement("div");
    arrow.innerHTML =
      '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M4.5 2.5v17.2l4.6-4.3 3 6.6 2.9-1.3-3-6.5h6.4z" fill="#111" stroke="#fff" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    arrow.style.cssText =
      "position:fixed;z-index:2147483647;left:-40px;top:-40px;width:26px;height:26px;pointer-events:none;filter:drop-shadow(0 1px 2px #0005);transform-origin:4px 2px;transition:transform 90ms ease";
    document.body.appendChild(arrow);
    window.addEventListener("mousemove", (event) => {
      arrow.style.left = `${event.clientX - 4}px`;
      arrow.style.top = `${event.clientY - 2}px`;
    }, true);
    window.addEventListener("mousedown", () => (arrow.style.transform = "scale(0.86)"), true);
    window.addEventListener("mouseup", () => (arrow.style.transform = "scale(1)"), true);
  });
}, !TAIL);
const page = await context.newPage();
t0 = Date.now(); // the video starts with the page
const FRAMES = join(OUT, `frames-${VIDEO}`);
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });
const frames = [];
const cdp = await context.newCDPSession(page);
cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
  const name = `f${String(frames.length).padStart(6, "0")}.jpg`;
  frames.push([name, Math.max(0, metadata.timestamp - t0 / 1000)]);
  writeFileSync(join(FRAMES, name), Buffer.from(data, "base64"));
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});
const startFilm = () =>
  cdp.send("Page.startScreencast", { format: "jpeg", quality: 93, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });

const pause = (ms) => page.waitForTimeout(ms);
const fire = (type, detail) =>
  page.evaluate(([name, data]) => window.dispatchEvent(new CustomEvent(name, { detail: data })), [type, detail]);
const cap = (count) => fire("suhail:rail", { cap: count });

// ---- A person's hand: eased pointer moves, a short hover, a press, slow scrolling ------------
const pointer = { x: 1500, y: 620 };
async function glide(x, y, ms) {
  const distance = Math.hypot(x - pointer.x, y - pointer.y);
  const duration = ms ?? Math.min(820, 300 + distance * 0.6);
  const steps = Math.max(12, Math.round(duration / 16));
  const from = { ...pointer };
  for (let step = 1; step <= steps; step++) {
    const k = step / steps;
    const eased = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    await page.mouse.move(from.x + (x - from.x) * eased, from.y + (y - from.y) * eased);
    await pause(duration / steps);
  }
  pointer.x = x;
  pointer.y = y;
}
/** Scrolls the element's own scroll area slowly until the element is in place. */
async function scrollTo(locator, block = "center", ms = 1400) {
  await locator.evaluate(
    (element, [where, duration]) =>
      new Promise((done) => {
        let area = element.parentElement;
        while (area && !(area.scrollHeight > area.clientHeight + 4 && /(auto|scroll)/.test(getComputedStyle(area).overflowY)))
          area = area.parentElement;
        const root = !area || area === document.body || area === document.documentElement;
        if (root) area = document.scrollingElement;
        const box = element.getBoundingClientRect();
        const frame = root ? { top: 0, height: window.innerHeight } : area.getBoundingClientRect();
        const delta = where === "start" ? box.top - frame.top - 28 : box.top + box.height / 2 - (frame.top + frame.height / 2);
        const from = area.scrollTop;
        const to = Math.max(0, Math.min(area.scrollHeight - area.clientHeight, from + delta));
        if (Math.abs(to - from) < 6) return done();
        const started = performance.now();
        const span = Math.min(2200, Math.max(duration, Math.abs(to - from) * 1.6));
        const step = (time) => {
          const k = Math.min(1, (time - started) / span);
          area.scrollTop = from + (to - from) * (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
          if (k < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    [block, ms],
  );
  await pause(350);
}
/** Move to the control like a person, rest on it, press it. Scrolls slowly first if it is out of view. */
async function click(locator, { settle = 380 } = {}) {
  await locator.waitFor({ timeout: 30000 });
  let box = await locator.boundingBox();
  if (!box || box.y < 0 || box.y + box.height > 1080) {
    await scrollTo(locator);
    box = await locator.boundingBox();
  }
  await glide(box.x + box.width / 2, box.y + box.height / 2);
  await pause(230);
  await page.mouse.down();
  await pause(90);
  await page.mouse.up();
  await pause(settle);
}
/** Types like a quick typist: a few characters at a time. */
const type = async (text, gap = 70) => {
  for (let at = 0; at < text.length; at += 3) {
    await page.keyboard.insertText(text.slice(at, at + 3));
    await pause(gap);
  }
};
const mode = async (label) => {
  const button = page.getByRole("button", { name: label === "Balanced" ? "Balanced view" : label, exact: true });
  if ((await button.getAttribute("aria-pressed")) !== "true") await click(button, { settle: 500 });
};
/** Wait until the backend itself has reported a step (the page marks it, whatever the rail shows). */
const reported = (index, states = "completed|waiting|failed") =>
  page
    .locator(".pipeline-step")
    .nth(index)
    .and(page.locator(states.split("|").map((state) => `[data-reported=${state}]`).join(",")))
    .waitFor({ timeout: 6 * 60 * 1000 });

/** One step: shown as finished on the rail, its records lit, held to be read. */
async function play(index, live = {}) {
  const cue = { ...cueOf(index), ...live };
  const selects = list(cue.select);
  await cap(index + 1);
  note(`step ${STEPS[index]} shown: ${cue.highlight?.length ?? 0} records lit`);
  await pause(150);
  // The selected record centres the map on it; the lit records show its relationships.
  if (selects[0]) await fire("suhail:select", { id: selects[0] });
  if (cue.highlight?.length) await fire("suhail:graph-highlight", { caseId, ids: cue.highlight });
  await pause(cue.hold_ms ?? BEAT[STEPS[index]]);
}
/** While the model is diagnosing: the journey on the map, then the relationships in the graph. */
async function views() {
  await mode("Map focus");
  await pause(1000);
  await mode("Graph focus");
  await pause(1200);
}
const settle = async (test, seconds) => {
  let current = await api(`/cases/${caseId}`);
  for (let tries = 0; test(current) && tries < seconds; tries++) {
    await pause(1000);
    current = await api(`/cases/${caseId}`);
  }
  return current;
};
const running = (d) => /OPEN|INVESTIGATING|RECOMMENDATION_READY|REOPENED/.test(d.workflow_state);
const hasPhoto = (d) => (d.evidence?.nodes ?? []).some((node) => node.id === MAP.photo_node);
/** Backstage: simulated time moves until `done(case)`; a skip is refused while an investigation runs. */
async function moveTime(done, body = {}) {
  for (let tries = 0; tries < 60; tries++) {
    const current = await api(`/cases/${caseId}`);
    if (done(current)) return current;
    const response = await post("/simulation/skip", body);
    note(`skip ${response.status}: ${JSON.stringify(await response.json().catch(() => ({}))).slice(0, 140)}`);
    if (response.status !== 200) await pause(4000);
  }
  return api(`/cases/${caseId}`);
}
/** Whatever happens, the backend is left with Auto off and the clock paused. */
const leave = async () => {
  if (TAIL) return;
  await post("/worker/pause").catch(() => {});
  await post("/simulation/pause").catch(() => {});
};
const row = () => page.getByTestId(`data-row-${caseId}`);
/** The cases that existed before the clock was started; the showcase case is a new one. */
let before = new Set();
async function findCase() {
  for (let tries = 0; tries < 60; tries++) {
    if (tries) await pause(500);
    const found = (await api("/cases/queue?scope=all&limit=100")).items.find(
      (item) => item.shipment_id === MAP.shipment_id && !before.has(item.case_id),
    );
    if (found) return found.case_id;
  }
  throw new Error(`${MAP.shipment_id} did not open a case`);
}
async function openCase() {
  await click(row(), { settle: 300 });
  await page.getByRole("heading", { level: 1 }).waitFor();
  await page.getByTestId("knowledge-graph").locator(".entity-node").first().waitFor({ timeout: 90000 });
  await pause(900);
  note("case opened");
}
async function operations() {
  // Before filming: the case page's code is loaded once, so opening a case later shows no blank frame.
  await page.goto(`${BASE}/app/investigation`);
  await page.waitForTimeout(2500);
  await page.getByRole("link", { name: "Operations", exact: true }).first().click();
  await page.locator(".environment-badge[data-dataset=synthetic]").waitFor({ timeout: 90000 });
  await page.waitForTimeout(1200);
  await startFilm();
  await waiting(page.locator(".environment-badge[data-dataset=synthetic]").waitFor({ timeout: 90000 }), 0);
  await page.mouse.move(pointer.x, pointer.y);
  await pause(900);
  before = new Set((await api("/cases/queue?scope=all&limit=100")).items.map((item) => item.case_id));
  // Backstage: the simulated clock starts at the speed the fixture was prepared for.
  await post("/simulation/start", { speed: Number(arg("speed", 60)), replay_mode: "timeline" });
  startedAt = new Date().toISOString();
  note(`clock started at ${startedAt}`);
  await click(page.getByRole("switch", { name: "Automatic investigation" }), { settle: 600 });
  note("Auto on, clock running");
}
async function canopus() {
  await click(page.getByRole("button", { name: "Open Canopus assistant" }), { settle: 600 });
  const panel = page.locator(".canopus-window");
  await click(panel.getByRole("button", { name: "Expand conversation workspace" }), { settle: 500 });
  const box = panel.getByRole("textbox", { name: "Ask Canopus about this case" });
  // The question box usually has the caret already; it is clicked only when it does not.
  if (!(await box.evaluate((element) => element === document.activeElement))) await click(box, { settle: 200 });
  await type(QUESTION);
  await pause(250);
  await click(panel.getByRole("button", { name: "Send question" }), { settle: 200 });
  note("question sent");
  await waiting(panel.getByTestId("canopus-answer").waitFor({ timeout: 150000 }), 0.6);
  note(`answer: ${(await panel.getByTestId("canopus-answer").locator(".chat-prose").innerText()).replace(/\s+/g, " ")}`);
  await pause(Number(arg("answer-hold", 3600)));
  await click(panel.getByRole("button", { name: "Minimize Canopus conversation" }), { settle: 400 });
  await glide(1180, 150, 600);
  // The closing page stays long enough to read its status line.
  await pause(VIDEO === "B" ? 2600 : 1500);
}
/** Video B: the newly arrived delivery records in the graph, the stored photograph, the operator's finding. */
async function proofAndFinding(detail) {
  const proofNode = (MAP.proof_nodes ?? []).find((id) => /PROOF/.test(id)) ?? MAP.photo_node;
  const lightProof = async () => {
    // The delivery proof with the records around it: attempt, recipient code, handover, photo.
    await fire("suhail:select", { id: proofNode });
    await fire("suhail:graph-highlight", { caseId, ids: MAP.proof_nodes ?? [MAP.photo_node] });
  };
  await mode("Graph focus");
  await lightProof();
  await pause(2200);
  // The photo record; its stored photograph sits in the record's inspector, below the workspace.
  await fire("suhail:select", { id: MAP.photo_node });
  await pause(500);
  const thumbnail = page.getByTestId("evidence-photo");
  await scrollTo(thumbnail, "center", 1600);
  await click(thumbnail, { settle: 400 });
  await pause(3600);
  await click(page.getByTestId("photo-modal").getByRole("button", { name: /close/i }), { settle: 500 });
  const finding = page.getByRole("button", { name: "Record a person's finding" }).first();
  if (flag("finding") && !detail.outcome && (await finding.count())) {
    // The operator's own step, through the normal control. The backend records it as a person's
    // finding and decides the case's state itself; the film shows what it serves.
    await scrollTo(finding, "center", 1500);
    await click(finding, { settle: 900 });
    const dialog = page.getByRole("dialog");
    await click(dialog.getByLabel("Human outcome type"), { settle: 500 });
    await click(page.getByRole("option", { name: "Delivery confirmed by a person" }), { settle: 500 });
    await click(dialog.locator("#human-finding"), { settle: 250 });
    await type(MAP.human_finding ?? "Proof photo and recipient code match the delivery record.");
    // Only the delivery proof itself is cited.
    const proof = dialog.locator(".human-evidence label").filter({ hasText: /PROOF/ });
    if (!(await proof.count())) throw new Error("the delivery proof is not offered in the finding dialog");
    await click(proof.first(), { settle: 600 });
    if (TAIL) {
      await click(dialog.getByRole("button", { name: "Cancel" }));
      note("rehearsal: finding not recorded");
    } else {
      await click(dialog.getByRole("button", { name: "Record finding" }), { settle: 300 });
      await dialog.waitFor({ state: "hidden", timeout: 30000 });
      await pause(1200);
      detail = await api(`/cases/${caseId}`);
      note(`person's finding: ${detail.outcome?.verification_status}; ${detail.brief?.lines?.find((line) => line.key === "status")?.text_en ?? ""}`);
    }
  }
  await cap(null);
  await lightProof();
  await scrollTo(page.getByRole("heading", { level: 1 }), "start", 1600);
  await pause(1200);
  return detail;
}

let caseId = arg("case");
let startedAt = new Date().toISOString();
try {
  if (TAIL) {
    await page.goto(`${BASE}/app/cases/${caseId}`);
    await startFilm();
    await page.getByTestId("knowledge-graph").locator(".entity-node").first().waitFor({ timeout: 90000 });
    await page.mouse.move(pointer.x, pointer.y);
    await pause(1500);
    if (VIDEO === "B") await proofAndFinding(await api(`/cases/${caseId}`));
    if (flag("ask-anyway")) await canopus();
  } else if (VIDEO === "A") {
    // ---- Video A: custody discrepancy, investigated and resolved -----------------------------
    await operations();
    caseId = await waiting(findCase());
    await waiting(row().waitFor({ timeout: 120000 }));
    await pause(1300);
    await openCase();
    for (let index = 0; index <= 5; index++) {
      // The diagnosis takes the model a while: the views are shown during that real wait.
      if (index === 2) await views();
      await waiting(reported(index));
      await play(index);
    }
    await waiting(reported(6, "completed|waiting|failed|running"));
    let detail = await waiting(settle(running, 300));
    note(`investigation ended in ${detail.workflow_state}`);
    await cap(7);
    if (detail.recommendation?.approvable && !(detail.executions ?? []).length) {
      // The policy holds this action for a person: the operator's approval, as a visible click.
      await pause(1200);
      await click(page.getByRole("button", { name: "Review & authorize" }), { settle: 1100 });
      await click(page.getByRole("dialog").getByRole("button", { name: "Authorize action" }));
      note("approved as the operator");
      detail = await waiting(settle((d) => !(d.executions ?? []).length, 60));
    }
    const sent = (detail.executions ?? []).length > 0;
    note(`request ${sent ? "sent" : "not sent: the case is with a person"}`);
    await play(6);
    if (sent) {
      const outcome = moveTime((d) => !!d.outcome || !/AWAITING_OUTCOME|ACTION_INITIATED/.test(d.workflow_state));
      if (MAP.phone) {
        // The phone shows the request this take actually recorded, to the recipient it recorded.
        const action = detail.brief?.actions?.at(-1) ?? {};
        const toDriver = action.recipient?.kind === "device" && /APP-DRV/.test(action.recipient?.id ?? "");
        note(`request recorded for ${action.recipient?.label_en ?? "an unnamed recipient"}; phone shows ${toDriver ? "the driver's app" : "the facility's device"}`);
        const { options, confirmation } = MAP.phone;
        const phone = toDriver
          ? {
              title: MAP.phone.title.replace(/^Suhail\s*[—-]\s*/, ""),
              body: MAP.phone.body,
              options,
              chosen: Math.max(0, typeof MAP.phone.chosen === "number" ? MAP.phone.chosen : options.indexOf(MAP.phone.chosen)),
              confirmation,
            }
          : {
              title: "Custody check required",
              body: `Shipment ${MAP.shipment_id}: ${detail.recommendation?.action_en ?? action.label_en ?? ""}`,
              options: [],
              chosen: 0,
              confirmation: "Check scan recorded",
            };
        await fire("suhail:phone", { step: 1, ...phone });
        await pause(2400);
        await fire("suhail:phone", { step: 2 });
        await pause(2100);
        if (toDriver) {
          await fire("suhail:phone", { step: 3 });
          await pause(900);
        }
        await fire("suhail:phone", { step: 4 });
        await pause(1500);
        detail = await waiting(outcome, 0.2);
        await pause(400);
        await fire("suhail:phone", { step: 0 });
        await pause(900);
      } else {
        detail = await waiting(outcome);
      }
      note(`outcome ${detail.outcome ? `${detail.outcome.verification_status} success ${detail.outcome.success}` : "none"}; state ${detail.workflow_state}`);
      if (detail.outcome) {
        await waiting(reported(7));
        // The record that arrived in THIS take (its id differs from the reference run's).
        const arrived = detail.outcome.evidence_ids ?? [];
        await play(7, arrived.length
          ? { select: null, highlight: [...(cueOf(7).highlight ?? []).filter((id) => !/-SIM-/.test(id)), ...arrived] }
          : {});
      }
    }
    await cap(null);
    await canopus();
  } else {
    // ---- Video B: late delivery proof, re-examined, left with a person -----------------------
    await operations();
    let detail;
    if (arg("resume")) {
      // The first investigation of this case already ran in this world (an interrupted take):
      // the film starts with the case already with a person, while another case enters the queue.
      caseId = arg("resume");
      await waiting((async () => {
        for (let tries = 0; tries < 60; tries++) {
          const fresh = (await api("/cases/queue?scope=all&limit=100")).items.find((item) => !before.has(item.case_id));
          if (fresh) return page.getByTestId(`data-row-${fresh.case_id}`).waitFor({ timeout: 60000 });
          await pause(500);
        }
      })());
      await pause(1500);
      detail = await api(`/cases/${caseId}`);
      note(`resumed: the case is ${detail.workflow_state} from the earlier first investigation`);
    } else {
      caseId = await waiting(findCase());
      await waiting(row().waitFor({ timeout: 120000 }));
      await pause(1100);
      // The first investigation runs while the queue is on screen; it ends with a person.
      detail = await waiting(settle(running, 300), 1.0);
      note(`first investigation ended in ${detail.workflow_state}`);
    }
    const at = await row().boundingBox();
    await glide(at ? at.x + 420 : 760, at ? at.y + at.height / 2 : 420, 800);
    await pause(1300);
    const firstRun = detail.last_run_id;
    // Backstage: the build clone's record of the first investigation, then simulated time runs
    // to the next morning, when the driver's phone uploads its records and Suhail reopens the
    // case. Auto stays on, so Suhail starts the second investigation by itself.
    detail = await waiting((async () => {
      if (arg("first-map") && !arg("resume"))
        try {
          execSync(arg("first-map").replace("STARTED", startedAt), { stdio: "ignore", timeout: 120000 });
          note("first investigation's evidence map saved");
        } catch (error) {
          note(`first evidence map not saved: ${String(error.message).slice(0, 120)}`);
        }
      const arrivedAt = await moveTime(hasPhoto, { max_hours: 24 });
      note(`device records in the graph: ${hasPhoto(arrivedAt)}; state ${arrivedAt.workflow_state}`);
      // Suhail picks the reopened case up by itself; if the queue holds it back, it is started
      // with the same request the "Investigate now" button sends.
      let current = arrivedAt;
      for (let tries = 0; tries < 25 && current.last_run_id === firstRun && current.workflow_state !== "INVESTIGATING"; tries++) {
        await pause(1000);
        current = await api(`/cases/${caseId}`);
      }
      if (current.last_run_id === firstRun && current.workflow_state !== "INVESTIGATING") {
        const response = await post(`/cases/${caseId}/investigate`, {});
        note(`second investigation requested by the script: ${response.status}`);
      } else note("second investigation started by Auto");
      // Time no longer needs to run fast.
      await post("/simulation/start", { speed: 1, replay_mode: "timeline" }).catch(() => {});
      return current;
    })(), 0.3);
    await pause(700);
    await openCase();
    for (let index = 0; index <= 5; index++) {
      await waiting(reported(index), index === 2 ? 1.5 : 0.4);
      await play(index);
    }
    await waiting(reported(6, "completed|waiting|failed|running"));
    detail = await waiting(settle(running, 300));
    note(`second investigation ended in ${detail.workflow_state}`);
    await play(6, { hold_ms: 1600 });
    detail = await proofAndFinding(detail);
    await canopus();
  }
  note("end of take");
} catch (error) {
  await leave();
  await browser.close();
  throw error;
}

// ---- Leave the backend as it should be: Auto off, clock paused ----------------------------
await leave();
const ended = now();
await cdp.send("Page.stopScreencast").catch(() => {});
await context.close();
await browser.close();
// ffmpeg's list of frames, each shown until the next one was painted.
const lines = ["ffconcat version 1.0"];
frames.forEach(([name, at], index) => {
  const until = frames[index + 1]?.[1] ?? ended;
  lines.push(`file 'frames-${VIDEO}/${name}'`, `duration ${Math.max(0.001, until - at).toFixed(4)}`);
});
if (frames.length) lines.push(`file 'frames-${VIDEO}/${frames.at(-1)[0]}'`);
writeFileSync(join(OUT, `suhail-video-${VIDEO}-frames.txt`), `${lines.join("\n")}\n`);
writeFileSync(join(OUT, `suhail-video-${VIDEO}-timeline.txt`), `${log.join("\n")}\n`);
// The film begins with its first frame, not with the page: times are shifted to the film's own clock.
const filmStart = frames[0]?.[1] ?? 0;
writeFileSync(
  join(OUT, `suhail-video-${VIDEO}-idle.json`),
  JSON.stringify(idle.map(([from, to]) => [+(from - filmStart).toFixed(2), +(to - filmStart).toFixed(2)]).filter(([, to]) => to > 0)),
);
writeFileSync(join(OUT, `suhail-video-${VIDEO}-film-start.txt`), String(filmStart));
console.log(`recorded ${frames.length} frames over ${ended.toFixed(1)} s`);
