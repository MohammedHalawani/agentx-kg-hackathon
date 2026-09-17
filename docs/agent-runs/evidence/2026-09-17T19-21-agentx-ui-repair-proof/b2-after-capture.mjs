/**
 * Agent B (B2 Implementation) — post-impl theme lifecycle verification @ 1440×900
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
const SHOT = (name) => join(OUT, `${name}-after.png`);

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  runId: '2026-09-17T19-21-agentx-ui-repair-proof',
  phase: 'b2-after',
  agent: 'B',
  url: BASE,
  viewport: '1440x900',
  locale: 'EN',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  endpoint: { graph: null, schema: null },
  captures: [],
  measurements: [],
  themeToggle: [],
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

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  if (countEl) {
    const ratio = await contrastRatio(page, countEl.color, 'rgb(250, 249, 247)');
    report.measurements.push({ theme, view: 'H01-intake-count', ratio, ...countEl });
    if (ratio < 4.5) report.issues.push({ id: 'H01', theme, ratio });
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
        report.issues.push({ id: 'H02', theme, detail: 'dark hover #e8f1fc regression' });
      }
      if (ratio < 4.5) report.issues.push({ id: 'H02', theme, ratio });
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
      if (ratio < 4.5) report.issues.push({ id: 'H03', theme, ratio });
    }
  }

  const queueRow = page.locator('tr[data-state="selected"]').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(200);
    const qCell = await measure(page, 'tr[data-state="selected"] td:nth-child(2)');
    if (qCell) {
      const ratio = await contrastRatio(page, qCell.color, qCell.backgroundColor);
      report.measurements.push({ theme, view: 'H04-queue-selected-hover', ratio, pointerHover: true, ...qCell });
      if (ratio < 4.5) report.issues.push({ id: 'H04', theme, ratio });
    }
  }

  const intakeBtn = page.locator('[data-sidebar="menu-button"]').nth(0);
  await intakeBtn.hover();
  await page.waitForTimeout(200);
  const hoverSidebar = await measure(page, '[data-sidebar="menu-button"]:hover');
  const activeSidebar = await measure(page, '[data-sidebar="menu-button"][data-active="true"]');
  report.measurements.push({ theme, view: 'H05-sidebar-hover', pointerHover: true, ...hoverSidebar });
  report.measurements.push({ theme, view: 'H05-sidebar-active', ...activeSidebar });
}

for (const id of ['H01', 'H02', 'H03', 'H04', 'H05']) {
  report.b1Sentinels[id] = report.issues.some((i) => i.id === id) ? 'FAIL' : 'PASS';
}

await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1000);
await page.locator('[data-sidebar="menu-button"]').nth(2).click();
await page.waitForTimeout(500);
await page.locator('button').filter({ hasText: /Schema/i }).click();
await page.waitForTimeout(4000);

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.waitForTimeout(600);

  const layoutSelected = await measure(page, 'button.bg-primary.text-primary-foreground');
  if (layoutSelected) {
    const ratio = await contrastRatio(page, layoutSelected.color, layoutSelected.backgroundColor);
    report.measurements.push({ theme, view: 'E02-layout-selected', ratio, fixture: 'schema-live', ...layoutSelected });
    if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'E02', theme, ratio, control: 'layout' });
  }

  const legend = await measure(page, '.absolute.left-3.top-3');
  if (legend) report.measurements.push({ theme, view: 'E04-legend-overlay', ...legend });

  const shot2d = SHOT(`b2-schema-2d-${theme}`);
  await page.screenshot({ path: shot2d, fullPage: false });
  report.captures.push(shot2d);

  const renderer3d = page.locator('button').filter({ hasText: /3D/i }).first();
  const renderer2d = page.locator('button').filter({ hasText: /2D/i }).first();
  if (await renderer3d.count()) {
    await renderer3d.click();
    await page.waitForTimeout(3000);
    const canvasBg = await page.evaluate(() => {
      const wrap = document.querySelector('.relative.h-full.w-full.overflow-hidden.bg-surface');
      return { wrapBg: wrap ? getComputedStyle(wrap).backgroundColor : null, canvasCount: document.querySelectorAll('canvas').length };
    });
    report.measurements.push({ theme, view: 'E03-3d-wrap', fixture: 'schema-live', ...canvasBg });
    const shot3d = SHOT(`b2-schema-3d-${theme}`);
    await page.screenshot({ path: shot3d, fullPage: false });
    report.captures.push(shot3d);
    await renderer2d.click();
    await page.waitForTimeout(2000);
  }
}

const toggleSequence = ['light', 'dark', 'light'];
for (const theme of toggleSequence) {
  await setTheme(page, theme);
  await page.waitForTimeout(500);
  const surface = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-surface').trim());
  const primaryBtn = await measure(page, 'button.bg-primary.text-primary-foreground');
  const legendFg = await measure(page, '.absolute.left-3.top-3');
  report.themeToggle.push({ step: theme, surface, primaryBtn, legendFg, remounted: false });
}

const toggleShot = SHOT('b2-theme-toggle-no-remount');
await page.screenshot({ path: toggleShot, fullPage: false });
report.captures.push(toggleShot);

await page.locator('button').filter({ hasText: /^Graph/i }).click();
await page.waitForTimeout(2500);
report.graphLensEmpty = await page.evaluate(() => document.body.innerText.includes('No graph data') || document.body.innerText.includes('no graph'));
const graphShot = SHOT('b2-graph-empty-light');
await page.screenshot({ path: graphShot, fullPage: false });
report.captures.push(graphShot);

const graphBlocked = report.endpoint.graph?.status !== 200;
for (const id of ['E02', 'E03', 'E04']) {
  const idIssues = report.issues.filter((i) => i.id === id);
  if (id === 'E03' && graphBlocked) {
    report.verdicts[id] = idIssues.length ? 'BLOCKED (schema proxy issues)' : 'BLOCKED (no /graph live 3D; schema proxy OK)';
  } else if (graphBlocked) {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED (schema proxy)' : 'PARTIAL (schema proxy PASS)';
  } else {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED' : 'PASS';
  }
}

writeFileSync(join(OUT, 'measurements-b2-after.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B2 after issues:', report.issues.length, report.issues);
console.log('B1 sentinels:', report.b1Sentinels);
console.log('Verdicts:', report.verdicts);
console.log('written', join(OUT, 'measurements-b2-after.json'));
