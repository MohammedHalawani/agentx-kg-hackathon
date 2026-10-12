/**
 * A closing shot: the case as the take left it, opened at the top of its page, with the newly
 * arrived delivery records lit in the graph. It runs nothing in the backend; it only looks.
 *
 *   node recording/ending.mjs --video B --case <case id> --map <evidence-map.json>
 */
import { chromium } from "playwright";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const VIDEO = arg("video", "B").toUpperCase();
const BASE = arg("base", "http://127.0.0.1:8022");
const MAP = JSON.parse(readFileSync(resolve(arg("map")), "utf-8"));
const OUT = resolve(arg("out", join(here, "out")));
const caseId = arg("case");
const FRAMES = join(OUT, `frames-${VIDEO}-end`);
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const browser = await chromium.launch({ channel: "chrome", args: ["--hide-scrollbars"] });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
await context.addInitScript(() => window.sessionStorage.setItem("suhail-director", "1"));
const page = await context.newPage();
const fire = (type, detail) =>
  page.evaluate(([name, data]) => window.dispatchEvent(new CustomEvent(name, { detail: data })), [type, detail]);
await page.goto(`${BASE}/app/cases/${caseId}`);
await page.getByTestId("knowledge-graph").locator(".entity-node").first().waitFor({ timeout: 90000 });
await page.waitForTimeout(2500);
const frames = [];
const cdp = await context.newCDPSession(page);
const t0 = Date.now();
cdp.on("Page.screencastFrame", ({ data, metadata, sessionId }) => {
  const name = `f${String(frames.length).padStart(6, "0")}.jpg`;
  frames.push([name, Math.max(0, metadata.timestamp - t0 / 1000)]);
  writeFileSync(join(FRAMES, name), Buffer.from(data, "base64"));
  cdp.send("Page.screencastFrameAck", { sessionId }).catch(() => {});
});
await cdp.send("Page.startScreencast", { format: "jpeg", quality: 93, maxWidth: 1920, maxHeight: 1080, everyNthFrame: 1 });
await page.waitForTimeout(700);
await fire("suhail:graph-highlight", { caseId, ids: MAP.proof_nodes ?? [] });
if (MAP.proof_nodes?.length) await fire("suhail:select", { id: MAP.proof_nodes.find((id) => /PROOF/.test(id)) ?? MAP.proof_nodes[0] });
await page.waitForTimeout(Number(arg("hold", 8000)));
const ended = (Date.now() - t0) / 1000;
await browser.close();
const lines = ["ffconcat version 1.0"];
frames.forEach(([name, at], index) => {
  const until = frames[index + 1]?.[1] ?? ended;
  lines.push(`file 'frames-${VIDEO}-end/${name}'`, `duration ${Math.max(0.001, until - at).toFixed(4)}`);
});
lines.push(`file 'frames-${VIDEO}-end/${frames.at(-1)[0]}'`);
writeFileSync(join(OUT, `suhail-video-${VIDEO}-end-frames.txt`), `${lines.join("\n")}\n`);
console.log(`ending shot: ${frames.length} frames over ${ended.toFixed(1)} s`);
