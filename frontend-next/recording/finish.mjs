/**
 * Turns a raw take into the MP4: removes the stretches the director marked as only waiting
 * (nothing is reordered or sped up), and encodes H.264 1920x1080 without sound.
 *
 *   node recording/finish.mjs --video A [--cut "12.5-20,31-40"] [--keep-idle] [--out recording/out]
 *
 * --cut adds ranges (seconds of the raw take) to remove; --keep-idle keeps the marked waits.
 */
import ffmpeg from "ffmpeg-static";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const arg = (name, fallback) => {
  const at = process.argv.indexOf(`--${name}`);
  return at > 0 ? process.argv[at + 1] : fallback;
};
const VIDEO = arg("video", "A").toUpperCase();
const OUT = resolve(arg("out", join(here, "out")));
const raw = join(OUT, `suhail-video-${VIDEO}-raw.webm`);
const idleFile = join(OUT, `suhail-video-${VIDEO}-idle.json`);
const cuts = [
  ...(process.argv.includes("--keep-idle") || !existsSync(idleFile)
    ? []
    : JSON.parse(readFileSync(idleFile, "utf-8"))),
  ...(arg("cut", "") || "")
    .split(",")
    .filter(Boolean)
    .map((range) => range.split("-").map(Number)),
]
  .filter(([from, to]) => to > from)
  .sort((a, b) => a[0] - b[0]);
// What stays is everything between the cuts.
const keep = [];
let at = 0;
for (const [from, to] of cuts) {
  if (from > at) keep.push([at, from]);
  at = Math.max(at, to);
}
keep.push([at, 1e6]);
const select = keep.map(([from, to]) => `between(t,${from},${to})`).join("+");
const target = join(OUT, `suhail-video-${VIDEO}.mp4`);
execFileSync(
  ffmpeg,
  ["-y", "-i", raw, "-vf", `select='${select}',setpts=N/FRAME_RATE/TB,fps=30,format=yuv420p`,
   "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-movflags", "+faststart", target],
  { stdio: ["ignore", "ignore", "inherit"] },
);
const removed = cuts.reduce((sum, [from, to]) => sum + (to - from), 0);
console.log(`${target}: removed ${removed.toFixed(1)} s of waiting in ${cuts.length} cuts`);
