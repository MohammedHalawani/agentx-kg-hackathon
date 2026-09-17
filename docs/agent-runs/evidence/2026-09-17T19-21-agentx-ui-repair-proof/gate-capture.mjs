/**
 * Agent D (Gate) — independent Playwright verification @ 1440×900
 * Candidate build: index-B9I8LKnG.css / index-Cy1Gdul3.js
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const CANDIDATE_CSS = 'index-B9I8LKnG.css';
const CANDIDATE_JS = 'index-Cy1Gdul3.js';

const SURFACES = { light: 'rgb(250, 249, 247)', dark: 'rgb(17, 19, 24)' };

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
    const rect = el.getBoundingClientRect();
    return {
      selector: sel,
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      className: el.className,
      text: (el.textContent || '').slice(0, 80),
      fontSize: cs.fontSize,
      fontWeight: cs.fontWeight,
      rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
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

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  url: BASE,
  viewport: '1440x900',
  phase: 'gate',
  agent: 'D',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  captures: [],
  measurements: [],
  issues: [],
  verdicts: {},
};

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}));

const servedCss = report.buildFingerprint.css.find((h) => h.includes('/assets/index-')) || '';
const servedJs = report.buildFingerprint.js.find((h) => h.includes('/assets/index-')) || '';
if (!servedCss.includes(CANDIDATE_CSS) || !servedJs.includes(CANDIDATE_JS)) {
  report.issues.push({
    id: 'BUILD',
    detail: `Served assets mismatch. Expected ${CANDIDATE_CSS}/${CANDIDATE_JS}, got ${servedCss} ${servedJs}`,
  });
}

// E02/E04 blocker probe
const graphStatus = await page.evaluate(async () => {
  try {
    const r = await fetch('/graph');
    return r.status;
  } catch {
    return -1;
  }
});
report.graphEndpointStatus = graphStatus;

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  // H01
  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground');
  if (countEl) {
    const ratio = await contrastRatio(page, countEl.color, countBg || SURFACES[theme]);
    report.measurements.push({ theme, view: 'H01-intake-count', ratio, color: countEl.color, bg: countBg, ...countEl });
    if (ratio < 4.5) report.issues.push({ id: 'H01', theme, ratio });
  }

  // H02 — pointer hover
  const caseBtn = page.locator('button').filter({ hasText: /SHP-/ }).first();
  if (await caseBtn.count()) {
    await caseBtn.hover();
    await page.waitForTimeout(300);
    const hoverBtn = await measure(page, 'button:hover');
    const hoverShot = join(OUT, `gate-intake-${theme}-hover.png`);
    await page.screenshot({ path: hoverShot, fullPage: false });
    report.captures.push(hoverShot);
    if (hoverBtn) {
      const ratio = await contrastRatio(page, hoverBtn.color, hoverBtn.backgroundColor);
      report.measurements.push({ theme, view: 'H02-intake-hover', ratio, pointerHover: true, ...hoverBtn });
      if (hoverBtn.backgroundColor.includes('232, 241, 252') && theme === 'dark') {
        report.issues.push({ id: 'H02', theme, detail: 'dark hover still #e8f1fc' });
      }
      if (ratio < 4.5) report.issues.push({ id: 'H02', theme, ratio });
    }
  }

  // Decisions view
  await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1500);

  // H03
  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const sel = await measure(page, 'button.border-primary\\/30');
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.measurements.push({ theme, view: 'H03-problem-selected', ratio, ...sel });
      if (ratio < 4.5) report.issues.push({ id: 'H03', theme, ratio, state: 'selected' });
    }
    await problemRow.hover();
    await page.waitForTimeout(200);
    const selHover = await measure(page, 'button.border-primary\\/30:hover');
    if (selHover) {
      const ratio = await contrastRatio(page, selHover.color, selHover.backgroundColor);
      report.measurements.push({ theme, view: 'H03-problem-selected-hover', ratio, pointerHover: true, ...selHover });
      if (ratio < 4.5) report.issues.push({ id: 'H03', theme, ratio, state: 'selected+hover' });
    }
    const problemRow2 = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).nth(1);
    if (await problemRow2.count()) {
      await problemRow2.hover();
      await page.waitForTimeout(200);
      const hoverProb = await measure(page, 'button:hover');
      if (hoverProb) {
        const ratio = await contrastRatio(page, hoverProb.color, hoverProb.backgroundColor);
        report.measurements.push({ theme, view: 'H03-problem-hover', ratio, pointerHover: true, ...hoverProb });
        if (ratio < 4.5) report.issues.push({ id: 'H03', theme, ratio, state: 'hover' });
      }
    }
  }

  // H04 — bottom queue table (data-state=selected), NOT matching-cases sub-table
  const queueRow = page.locator('tr[data-state="selected"]').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(200);
    const qCell = await measure(page, 'tr[data-state="selected"] td:nth-child(2)');
    const rowBg = await effectiveBg(page, 'tr[data-state="selected"]');
    if (qCell) {
      const ratio = await contrastRatio(page, qCell.color, rowBg || qCell.backgroundColor);
      report.measurements.push({
        theme,
        view: 'H04-queue-selected-hover',
        ratio,
        cellColor: qCell.color,
        rowBg,
        selector: 'tr[data-state="selected"] td (main queue)',
        pointerHover: true,
        ...qCell,
      });
      if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H04', theme, ratio });
      if (qCell.color.includes('32, 32, 30') && theme === 'light' && rowBg?.includes('232, 241, 252')) {
        // expected inherit: accent-foreground on accent bg
      } else if (theme === 'light' && qCell.color === 'rgb(32, 32, 30)' && !rowBg?.includes('232, 241, 252')) {
        report.issues.push({ id: 'H04', theme, detail: 'cell not inheriting selected row foreground' });
      }
    }
    const qShot = join(OUT, `gate-decisions-${theme}-queue-selected-hover.png`);
    await page.screenshot({ path: qShot, fullPage: false });
    report.captures.push(qShot);
  } else {
    // select first main-queue row if none selected
    const mainQueueRow = page.locator('table').filter({ has: page.locator('th') }).last().locator('tbody tr').first();
    if (await mainQueueRow.count()) {
      await mainQueueRow.click();
      await mainQueueRow.hover();
      await page.waitForTimeout(200);
      const qCell = await measure(page, 'tr[data-state="selected"] td:nth-child(2)');
      const rowBg = await effectiveBg(page, 'tr[data-state="selected"]');
      if (qCell) {
        const ratio = await contrastRatio(page, qCell.color, rowBg || qCell.backgroundColor);
        report.measurements.push({ theme, view: 'H04-queue-selected-hover', ratio, cellColor: qCell.color, rowBg, pointerHover: true, ...qCell });
        if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H04', theme, ratio });
      }
      const qShot = join(OUT, `gate-decisions-${theme}-queue-selected-hover.png`);
      await page.screenshot({ path: qShot, fullPage: false });
      report.captures.push(qShot);
    }
  }

  // H05
  const intakeBtn = page.locator('[data-sidebar="menu-button"]').nth(0);
  await intakeBtn.hover();
  await page.waitForTimeout(200);
  const hoverSidebar = await measure(page, '[data-sidebar="menu-button"]:hover');
  const activeSidebar = await measure(page, '[data-sidebar="menu-button"][data-active="true"]');
  report.measurements.push({ theme, view: 'H05-sidebar-hover', pointerHover: true, ...hoverSidebar });
  report.measurements.push({ theme, view: 'H05-sidebar-active', ...activeSidebar });
  if (hoverSidebar && activeSidebar && hoverSidebar.backgroundColor === activeSidebar.backgroundColor) {
    report.issues.push({ id: 'H05', theme, detail: 'hover bg equals active bg' });
  }
  const sideShot = join(OUT, `gate-sidebar-${theme}-hover.png`);
  await page.screenshot({ path: sideShot, fullPage: false });
  report.captures.push(sideShot);

  // H06
  await page.evaluate(() => {
    const cards = [...document.querySelectorAll('[data-slot="card"]')];
    const esc = cards.find((c) => c.textContent?.toLowerCase().includes('escalat'));
    esc?.scrollIntoView({ block: 'center' });
  });
  await page.waitForTimeout(300);
  const emptyIcon = await measure(page, '[data-slot="empty-icon"]');
  const emptyIconBg = await effectiveBg(page, '[data-slot="empty-icon"]');
  if (emptyIcon) {
    const ratio = await contrastRatio(page, emptyIcon.color, emptyIconBg || emptyIcon.backgroundColor);
    report.measurements.push({ theme, view: 'H06-escalations-empty-icon', ratio, bg: emptyIconBg, ...emptyIcon });
    if (emptyIconBg?.includes('232, 241, 252') && theme === 'dark') {
      report.issues.push({ id: 'H06', theme, detail: 'empty icon light chip in dark' });
    }
    if (ratio < 4.5) report.issues.push({ id: 'H06', theme, ratio });
  }
  const h06Shot = join(OUT, `gate-escalations-${theme}-empty.png`);
  await page.screenshot({ path: h06Shot, fullPage: false });
  report.captures.push(h06Shot);

  // E01
  await page.locator('[data-sidebar="menu-button"]').nth(2).click();
  await page.waitForTimeout(2500);
  const lensText = await measure(page, 'button .relative.z-10');
  const lensBgEl = await measure(page, 'button .absolute.inset-0.rounded-md.bg-primary');
  if (lensText && lensBgEl) {
    const ratio = await contrastRatio(page, lensText.color, lensBgEl.backgroundColor);
    report.measurements.push({
      theme,
      view: 'E01-explore-lens',
      ratio,
      textColor: lensText.color,
      pillBg: lensBgEl.backgroundColor,
      fontSize: lensText.fontSize,
      fontWeight: lensText.fontWeight,
    });
    if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'E01', theme, ratio });
  }
  const e01Shot = join(OUT, `gate-explore-${theme}-lens.png`);
  await page.screenshot({ path: e01Shot, fullPage: false });
  report.captures.push(e01Shot);
}

// Per-issue gate verdicts
const issueIds = ['H01', 'H02', 'H03', 'H04', 'H05', 'H06', 'E01', 'E02', 'E03', 'E04'];
for (const id of issueIds) {
  const idIssues = report.issues.filter((i) => i.id === id);
  if (id === 'E02' || id === 'E04') {
    report.verdicts[id] = graphStatus === 200 ? (idIssues.length ? 'FAIL' : 'PASS') : 'BLOCKED';
  } else if (id === 'E03') {
    report.verdicts[id] = graphStatus === 200 ? (idIssues.length ? 'FAIL' : 'PASS') : 'BLOCKED (code PASS)';
  } else {
    report.verdicts[id] = idIssues.length ? 'FAIL' : 'PASS';
  }
}

writeFileSync(join(OUT, 'measurements-gate.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('Gate issues:', report.issues.length, report.issues);
console.log('Verdicts:', report.verdicts);
console.log('written', join(OUT, 'measurements-gate.json'));
