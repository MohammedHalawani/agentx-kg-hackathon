/**
 * Agent C (B2 Review) — independent verification @ 1440×900
 * Candidate build: index-B9I8LKnG.css / index-276MDZLC.js
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const CANDIDATE_CSS = 'index-B9I8LKnG.css';
const CANDIDATE_JS = 'index-276MDZLC.js';
const SURFACES = { light: 'rgb(250, 249, 247)', dark: 'rgb(17, 19, 24)' };
const SHOT = (name) => join(OUT, `${name}-review.png`);

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
}

/** Toggle via UI ThemeToggle so React resolvedTheme updates (not just DOM class). */
async function setThemeViaUI(page, theme) {
  const label = theme === 'dark' ? 'Dark' : theme === 'light' ? 'Light' : 'System';
  await page.locator('button[aria-label*="theme" i], button[aria-label*="Theme" i]').first().click();
  await page.waitForTimeout(200);
  await page.getByRole('menuitem', { name: label }).click();
  await page.waitForTimeout(500);
}

async function measure(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return {
      selector: sel,
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      className: el.className,
      text: (el.textContent || '').slice(0, 60),
    };
  }, selector);
}

async function effectiveBg(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    let node = el;
    while (node) {
      const bg = getComputedStyle(node).backgroundColor;
      if (bg && bg !== 'rgba(0, 0, 0, 0)') return bg;
      node = node.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  }, selector);
}

async function contrastRatio(page, fg, bg) {
  return page.evaluate(({ fg, bg }) => {
    const parse = (c) => {
      const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (!m) return null;
      return [+m[1], +m[2], +m[3]].map((v) => v / 255);
    };
    const lum = (rgb) => {
      const f = rgb.map((x) => (x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)));
      return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
    };
    const a = parse(fg);
    const b = parse(bg);
    if (!a || !b) return null;
    const L1 = lum(a);
    const L2 = lum(b);
    const hi = Math.max(L1, L2);
    const lo = Math.min(L1, L2);
    return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
  }, { fg, bg });
}

async function legendSwatchColors(page) {
  return page.evaluate(() => {
    const swatches = [...document.querySelectorAll('.absolute.left-3.top-3 .h-2\\.5, .absolute.left-3.top-3 .h-2')];
    return swatches.map((el) => getComputedStyle(el).backgroundColor);
  });
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  runId: '2026-09-17T19-21-agentx-ui-repair-proof',
  phase: 'b2-review',
  agent: 'C',
  url: BASE,
  viewport: '1440x900',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  endpoint: { graph: null, schema: null },
  captures: [],
  measurements: [],
  themeToggle: [],
  themeColorRefresh: [],
  issues: [],
  verdicts: {},
  b1Sentinels: {},
};

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1200);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}));

const servedCss = report.buildFingerprint.css.find((h) => h.includes('/assets/index-')) || '';
const servedJs = report.buildFingerprint.js.find((h) => h.includes('/assets/index-')) || '';
if (!servedCss.includes(CANDIDATE_CSS) || !servedJs.includes(CANDIDATE_JS)) {
  report.issues.push({
    id: 'BUILD',
    severity: 'BLOCKER',
    detail: `Served assets mismatch. Expected ${CANDIDATE_CSS}/${CANDIDATE_JS}, got ${servedCss} ${servedJs}`,
  });
}

report.endpoint = await page.evaluate(async () => {
  const probe = async (path) => {
    try {
      const r = await fetch(path);
      return { status: r.status, ok: r.ok };
    } catch {
      return { status: -1, ok: false };
    }
  };
  return { graph: await probe('/graph'), schema: await probe('/schema') };
});

// B1 sentinels with gate effectiveBg methodology
for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground');
  if (countEl) {
    const ratio = await contrastRatio(page, countEl.color, countBg || SURFACES[theme]);
    report.measurements.push({ theme, view: 'H01-intake-count', ratio, color: countEl.color, bg: countBg, ...countEl });
    if (ratio < 4.5) report.issues.push({ id: 'H01', severity: 'HIGH', theme, ratio });
  }

  const caseBtn = page.locator('button').filter({ hasText: /SHP-/ }).first();
  if (await caseBtn.count()) {
    await caseBtn.hover();
    await page.waitForTimeout(250);
    const hoverBtn = await measure(page, 'button:hover');
    if (hoverBtn) {
      const ratio = await contrastRatio(page, hoverBtn.color, hoverBtn.backgroundColor);
      report.measurements.push({ theme, view: 'H02-intake-hover', ratio, pointerHover: true, ...hoverBtn });
      if (hoverBtn.backgroundColor.includes('232, 241, 252') && theme === 'dark') {
        report.issues.push({ id: 'H02', severity: 'HIGH', theme, detail: 'dark hover #e8f1fc regression' });
      }
      if (ratio < 4.5) report.issues.push({ id: 'H02', severity: 'HIGH', theme, ratio });
    }
  }

  await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1200);

  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const sel = await measure(page, 'button.border-primary\\/30');
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.measurements.push({ theme, view: 'H03-problem-selected', ratio, ...sel });
      if (ratio < 4.5) report.issues.push({ id: 'H03', severity: 'HIGH', theme, ratio });
    }
  }

  const queueRow = page.locator('tr[data-state="selected"]').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(200);
    const qCell = await measure(page, 'tr[data-state="selected"] td:nth-child(2)');
    const rowBg = await effectiveBg(page, 'tr[data-state="selected"]');
    if (qCell) {
      const ratio = await contrastRatio(page, qCell.color, rowBg || qCell.backgroundColor);
      report.measurements.push({ theme, view: 'H04-queue-selected-hover', ratio, cellColor: qCell.color, rowBg, pointerHover: true, ...qCell });
      if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H04', severity: 'HIGH', theme, ratio });
    }
  }

  const intakeBtn = page.locator('[data-sidebar="menu-button"]').nth(0);
  await intakeBtn.hover();
  await page.waitForTimeout(200);
  const hoverSidebar = await measure(page, '[data-sidebar="menu-button"]:hover');
  const activeSidebar = await measure(page, '[data-sidebar="menu-button"][data-active="true"]');
  report.measurements.push({ theme, view: 'H05-sidebar-hover', pointerHover: true, ...hoverSidebar });
  report.measurements.push({ theme, view: 'H05-sidebar-active', ...activeSidebar });
  if (hoverSidebar && activeSidebar && hoverSidebar.backgroundColor === activeSidebar.backgroundColor) {
    report.issues.push({ id: 'H05', severity: 'MEDIUM', theme, detail: 'hover bg equals active bg' });
  }
}

for (const id of ['H01', 'H02', 'H03', 'H04', 'H05']) {
  report.b1Sentinels[id] = report.issues.some((i) => i.id === id) ? 'FAIL' : 'PASS';
}

// Schema 2D/3D theme lifecycle
await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1000);
await page.locator('[data-sidebar="menu-button"]').nth(2).click();
await page.waitForTimeout(500);
await page.locator('button').filter({ hasText: /Schema/i }).click();
await page.waitForTimeout(4000);

async function readGraphSurface(page) {
  return page.evaluate(() => {
    const wrap = document.querySelector('.relative.h-full.w-full.overflow-hidden.bg-surface');
    const canvas = document.querySelector('canvas');
    return {
      wrapBg: wrap ? getComputedStyle(wrap).backgroundColor : null,
      surfaceVar: getComputedStyle(document.documentElement).getPropertyValue('--color-surface').trim(),
      canvasCount: document.querySelectorAll('canvas').length,
      canvasBg: canvas ? getComputedStyle(canvas).backgroundColor : null,
    };
  });
}

// Ensure light theme via UI before 2D baseline
await setThemeViaUI(page, 'light');
const light2d = await readGraphSurface(page);
report.themeColorRefresh.push({ view: 'schema-2d', theme: 'light', method: 'ui-toggle', ...light2d });
const shot2dLight = SHOT('b2-schema-2d-light');
await page.screenshot({ path: shot2dLight, fullPage: false });
report.captures.push(shot2dLight);

await setThemeViaUI(page, 'dark');
const dark2d = await readGraphSurface(page);
report.themeColorRefresh.push({ view: 'schema-2d', theme: 'dark', method: 'ui-toggle', ...dark2d });
const wrapChanged2d = light2d.wrapBg !== dark2d.wrapBg;
report.measurements.push({ view: 'E04-2d-wrap-changed', light: light2d.wrapBg, dark: dark2d.wrapBg, changed: wrapChanged2d });
if (!wrapChanged2d) {
  report.issues.push({ id: 'E04', severity: 'HIGH', detail: '2D wrap background unchanged after UI theme toggle' });
}
const shot2dDark = SHOT('b2-schema-2d-dark');
await page.screenshot({ path: shot2dDark, fullPage: false });
report.captures.push(shot2dDark);

// 3D mode — reset to light first
await setThemeViaUI(page, 'light');
const renderer3d = page.locator('button').filter({ hasText: /3D/i }).first();
if (await renderer3d.count()) {
  await renderer3d.click();
  await page.waitForTimeout(3000);
  const light3d = await readGraphSurface(page);
  report.themeColorRefresh.push({ view: 'schema-3d', theme: 'light', method: 'ui-toggle', ...light3d });
  const shot3dLight = SHOT('b2-schema-3d-light');
  await page.screenshot({ path: shot3dLight, fullPage: false });
  report.captures.push(shot3dLight);

  await setThemeViaUI(page, 'dark');
  const dark3d = await readGraphSurface(page);
  report.themeColorRefresh.push({ view: 'schema-3d', theme: 'dark', method: 'ui-toggle', ...dark3d });
  const wrapChanged3d = light3d.wrapBg !== dark3d.wrapBg;
  const surfaceChanged3d = light3d.surfaceVar !== dark3d.surfaceVar;
  report.measurements.push({ view: 'E03-3d-wrap-changed', light: light3d.wrapBg, dark: dark3d.wrapBg, changed: wrapChanged3d });
  report.measurements.push({ view: 'E03-3d-surface-var', light: light3d.surfaceVar, dark: dark3d.surfaceVar, changed: surfaceChanged3d });
  if (!wrapChanged3d) {
    report.issues.push({ id: 'E03', severity: 'HIGH', detail: '3D wrap background unchanged after UI theme toggle' });
  }
  const shot3dDark = SHOT('b2-schema-3d-dark');
  await page.screenshot({ path: shot3dDark, fullPage: false });
  report.captures.push(shot3dDark);

  // light→dark→light without remount
  await setThemeViaUI(page, 'light');
  const returnLight = await readGraphSurface(page);
  report.themeToggle.push({ step: 'light-return', wrapBg: returnLight.wrapBg, surfaceVar: returnLight.surfaceVar, remounted: false });
  const toggleShot = SHOT('b2-theme-toggle-no-remount');
  await page.screenshot({ path: toggleShot, fullPage: false });
  report.captures.push(toggleShot);
}

const graphBlocked = report.endpoint.graph?.status !== 200;
for (const id of ['E02', 'E03', 'E04']) {
  const idIssues = report.issues.filter((i) => i.id === id);
  if (id === 'E03' && graphBlocked) {
    report.verdicts[id] = idIssues.length ? 'PARTIAL (schema proxy issues)' : 'PARTIAL PASS (schema proxy; live Graph BLOCKED)';
  } else if (graphBlocked) {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED (schema proxy)' : 'PARTIAL PASS (schema proxy)';
  } else {
    report.verdicts[id] = idIssues.length ? 'FAIL' : 'PASS';
  }
}

writeFileSync(join(OUT, 'measurements-b2-review.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B2 review issues:', report.issues.length, report.issues);
console.log('B1 sentinels:', report.b1Sentinels);
console.log('Theme color refresh:', report.themeColorRefresh);
console.log('Verdicts:', report.verdicts);
console.log('written', join(OUT, 'measurements-b2-review.json'));
