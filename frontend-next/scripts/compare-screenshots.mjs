/**
 * Visual regression against the original lab: compares the lab screenshots the browser suite
 * regenerates on this codebase with the original lab's committed screenshots, pixel by pixel.
 *
 *   node scripts/compare-screenshots.mjs <dir-with-regenerated-png> [git-ref]
 *
 * A pixel differs when any channel differs by more than 16 (anti-aliasing noise is ignored).
 */
import { execFileSync } from "node:child_process";
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { chromium } from "@playwright/test";

const [regenerated, ref = "HEAD"] = process.argv.slice(2);
if (!regenerated) throw new Error("Pass the directory of regenerated screenshots.");
const names = readdirSync(regenerated)
  .filter((name) => name.startsWith("final-") && name.endsWith(".png"))
  .sort();
const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage();
let worst = 0;
for (const name of names) {
  const original = execFileSync(
    "git",
    ["show", `${ref}:frontend-next/screenshots/${name}`],
    { maxBuffer: 1 << 26 },
  );
  const current = readFileSync(path.join(regenerated, name));
  if (original.equals(current)) {
    console.log(`identical file   ${name}`);
    continue;
  }
  const result = await page.evaluate(
    async ([a, b]) => {
      const load = async (data) => {
        const image = new Image();
        image.src = `data:image/png;base64,${data}`;
        await image.decode();
        const canvas = new OffscreenCanvas(image.width, image.height);
        const context = canvas.getContext("2d");
        context.drawImage(image, 0, 0);
        return context.getImageData(0, 0, image.width, image.height);
      };
      const [x, y] = [await load(a), await load(b)];
      if (x.width !== y.width || x.height !== y.height)
        return { size: `${x.width}x${x.height} vs ${y.width}x${y.height}` };
      let different = 0;
      for (let i = 0; i < x.data.length; i += 4)
        if (
          Math.abs(x.data[i] - y.data[i]) > 16 ||
          Math.abs(x.data[i + 1] - y.data[i + 1]) > 16 ||
          Math.abs(x.data[i + 2] - y.data[i + 2]) > 16
        )
          different += 1;
      return { ratio: different / (x.width * x.height) };
    },
    [original.toString("base64"), current.toString("base64")],
  );
  if (result.size) {
    console.log(`SIZE DIFFERS     ${name}  ${result.size}`);
    worst = 1;
  } else {
    worst = Math.max(worst, result.ratio);
    console.log(
      `${(result.ratio * 100).toFixed(3).padStart(7)}% pixels  ${name}`,
    );
  }
}
await browser.close();
console.log(`\n${names.length} screenshots compared; largest difference ${(worst * 100).toFixed(3)}% of pixels`);
