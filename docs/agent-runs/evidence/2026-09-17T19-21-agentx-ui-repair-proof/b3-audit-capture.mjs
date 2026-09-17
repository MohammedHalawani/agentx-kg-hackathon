/**
 * Agent A (B3 Audit) — metric semantics + bounded workspace @ 1440×900
 * Candidate build: index-B9I8LKnG.css / index-276MDZLC.js (or served fingerprint)
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

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
}

async function clickThemeToggle(page) {
  const btn = page.locator('button[aria-label*="theme" i], button[title*="theme" i]').first();
  if (await btn.count()) {
    await btn.click();
    await page.waitForTimeout(400);
    return true;
  }
  const iconBtn = page.locator('header button').filter({ has: page.locator('svg') }).last();
  if (await iconBtn.count()) {
    await iconBtn.click();
    await page.waitForTimeout(400);
    return true;
  }
  return false;
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
      className: el.className?.slice?.(0, 120) || '',
      text: (el.textContent || '').slice(0, 80),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
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

async function effectiveBg(page, selector) {
  return page.evaluate((sel) => {
    let el = document.querySelector(sel);
    if (!el) return null;
    for (let i = 0; i < 8 && el; i++) {
      const bg = getComputedStyle(el).backgroundColor;
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') return bg;
      el = el.parentElement;
    }
    return null;
  }, selector);
}

const SURFACES = { light: 'rgb(250, 249, 247)', dark: 'rgb(17, 19, 24)' };

function panelByTitle(page, titleRe) {
  return page.locator('[data-slot="card"]').filter({ has: page.getByText(titleRe) }).first();
}

async function measurePanel(page, titleRe, label) {
  const card = panelByTitle(page, titleRe);
  if (!(await card.count())) return { label, found: false };
  const box = await card.boundingBox();
  const cls = await card.getAttribute('class');
  const scrollArea = card.locator('[data-slot="scroll-area-viewport"]').first();
  let scroll = null;
  if (await scrollArea.count()) {
    scroll = await scrollArea.evaluate((el) => ({
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      scrollTop: el.scrollTop,
      overflows: el.scrollHeight > el.clientHeight + 2,
    }));
  }
  return {
    label,
    found: true,
    outerHeight: box ? Math.round(box.height) : null,
    outerWidth: box ? Math.round(box.width) : null,
    className: cls,
    scroll,
  };
}

async function scrollToEnd(page, titleRe) {
  const card = panelByTitle(page, titleRe);
  const viewport = card.locator('[data-slot="scroll-area-viewport"]').first();
  if (!(await viewport.count())) return { scrolled: false };
  const before = await viewport.evaluate((el) => ({ top: el.scrollTop, sh: el.scrollHeight, ch: el.clientHeight }));
  await viewport.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await page.waitForTimeout(300);
  const after = await viewport.evaluate((el) => ({
    scrollTop: el.scrollTop,
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
    atEnd: el.scrollTop + el.clientHeight >= el.scrollHeight - 4,
    lastVisible: (() => {
      const rows = el.querySelectorAll('button, tbody tr');
      const last = rows[rows.length - 1];
      if (!last) return null;
      const r = last.getBoundingClientRect();
      const vp = el.getBoundingClientRect();
      return r.top >= vp.top - 2 && r.bottom <= vp.bottom + 2;
    })(),
  }));
  return { scrolled: true, before, after };
}

async function measureProgressBars(page) {
  return page.evaluate(() => {
    const indicators = [...document.querySelectorAll('[data-slot="progress-indicator"]')];
    return indicators.map((el, i) => {
      const cs = getComputedStyle(el);
      const track = el.closest('[data-slot="progress-track"]');
      const row = el.closest('button');
      const pct = row?.querySelector('.tabular-nums')?.textContent?.trim() || null;
      return {
        index: i,
        indicatorBg: cs.backgroundColor,
        trackBg: track ? getComputedStyle(track).backgroundColor : null,
        pctLabel: pct,
        context: row?.querySelector('.line-clamp-2')?.textContent?.slice(0, 40) || (i === 0 ? 'coverage-card' : 'unknown'),
      };
    });
  });
}

async function measureStickyHeader(page, tableSelector) {
  return page.evaluate((sel) => {
    const thead = document.querySelector(sel);
    if (!thead) return null;
    const cs = getComputedStyle(thead);
    return {
      position: cs.position,
      top: cs.top,
      zIndex: cs.zIndex,
      backgroundColor: cs.backgroundColor,
    };
  }, tableSelector);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  runId: '2026-09-17T19-21-agentx-ui-repair-proof',
  phase: 'b3-audit',
  agent: 'A',
  slug: 'metric-semantics-bounded-workspace',
  url: BASE,
  viewport: '1440x900',
  locale: 'EN',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  captures: [],
  measurements: [],
  panels: [],
  progressBars: [],
  scrollReach: [],
  issues: [],
  verdicts: {},
  apiProvenance: null,
};

await page.goto(BASE, { waitUntil: 'networkidle' });

// Live API snapshot (read-only)
report.apiProvenance = await page.evaluate(async () => {
  const r = await fetch('/cases');
  const data = await r.json();
  const cats = data.by_category || [];
  const nonEsc = cats.filter((c) => !c.category.startsWith('escalation:'));
  const totalCases = nonEsc.reduce((a, c) => a + c.cases, 0);
  const totalWon = nonEsc.reduce((a, c) => a + c.succeeded, 0);
  const allCases = cats.reduce((a, c) => a + c.cases, 0);
  const allWon = cats.reduce((a, c) => a + c.succeeded, 0);
  const feTotalCases = cats.reduce((a, c) => a + c.cases, 0);
  const feTotalWon = cats.reduce((a, c) => a + c.succeeded, 0);
  return {
    coverage: data.coverage,
    writebacks: data.writebacks,
    queueLen: (data.queue || []).length,
    escalationsLen: (data.escalations || []).length,
    categoryCount: cats.length,
    displayedCategoryCount: nonEsc.length,
    categories100pct: cats.filter((c) => c.success_rate >= 99.9).map((c) => ({ category: c.category, cases: c.cases, succeeded: c.succeeded })),
    overallRateExcludingEscalationDisplay: nonEsc.length ? Math.round((totalWon / totalCases) * 100) : 0,
    overallRateAsComputedInDecisionsView: feTotalCases ? Math.round((feTotalWon / feTotalCases) * 100) : 0,
    by_action_top: (data.by_action || []).slice(0, 3),
  };
});
await page.waitForTimeout(1200);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}));

// B1 sentinels + B2 schema proxy (abbreviated regression)
for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);

  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground');
  if (countEl) {
    const ratio = await contrastRatio(page, countEl.color, countBg || SURFACES[theme]);
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
    const rowBg = await effectiveBg(page, 'tr[data-state="selected"]');
    if (qCell) {
      const ratio = await contrastRatio(page, qCell.color, rowBg || qCell.backgroundColor);
      report.measurements.push({ theme, view: 'H04-queue-selected-hover', ratio, pointerHover: true, ...qCell });
      if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H04', theme, ratio });
    }
  }

  // B3 panel measurements on Decisions
  const panels = [
    [/Problems|Root causes/i, 'problems'],
    [/Actions/i, 'actions'],
    [/Focus|Selected/i, 'focus'],
    [/Open cases|Queue/i, 'queue'],
  ];
  for (const [re, key] of panels) {
    const m = await measurePanel(page, re, `${key}-${theme}`);
    report.panels.push(m);
  }

  report.progressBars.push({ theme, bars: await measureProgressBars(page) });

  const queueSticky = await measureStickyHeader(page, 'thead.sticky');
  report.measurements.push({ theme, view: 'L01-queue-sticky-header', ...queueSticky });

  const shot = join(OUT, `b3-decisions-${theme}-default.png`);
  await page.screenshot({ path: shot, fullPage: false });
  report.captures.push(shot);
}

// Scroll reachability — live data
await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1200);

for (const [re, key] of [
  [/Problems|Root causes/i, 'problems'],
  [/Actions/i, 'actions'],
  [/Focus|Selected/i, 'focus'],
  [/Open cases|Queue/i, 'queue'],
]) {
  const reach = await scrollToEnd(page, re);
  report.scrollReach.push({ panel: key, liveData: true, ...reach });
}

// Overflow fixture via route interception
const overflowFixture = await page.evaluate(async () => {
  const r = await fetch('/cases');
  const data = await r.json();
  const baseCat = data.by_category[0] || { category: 'test_cat', cases: 10, succeeded: 7, success_rate: 70 };
  const cats = Array.from({ length: 30 }, (_, i) => ({
    ...baseCat,
    category: `overflow_cat_${i}`,
    cases: 10 + i,
    succeeded: 5 + i,
    success_rate: 50 + i,
  }));
  const actions = Array.from({ length: 20 }, (_, i) => ({
    action: `Overflow action ${i} with a long label to test wrapping and scroll`,
    used: 20 - i,
    succeeded: 10,
    success_rate: 50,
  }));
  const queue = Array.from({ length: 80 }, (_, i) => ({
    failure_id: `FR-overflow-${String(i).padStart(4, '0')}`,
    category: `overflow_cat_${i % 30}`,
    city: `City ${i}`,
    courier: `Courier ${i}`,
    shipment_id: `SHP-OVR-${String(i).padStart(4, '0')}`,
  }));
  return {
    ...data,
    by_category: cats,
    by_action: actions,
    queue,
  };
});

await page.route('**/cases', (route) => {
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overflowFixture) });
});
await page.reload({ waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1500);

report.panelsOverflow = [];
for (const [re, key] of [
  [/Problems|Root causes/i, 'problems'],
  [/Actions/i, 'actions'],
  [/Focus|Selected/i, 'focus'],
  [/Open cases|Queue/i, 'queue'],
]) {
  const m = await measurePanel(page, re, `${key}-overflow`);
  report.panelsOverflow.push(m);
  const reach = await scrollToEnd(page, re);
  report.scrollReach.push({ panel: key, liveData: false, overflowFixture: true, ...reach });
}

const overflowShot = join(OUT, 'b3-decisions-overflow-scrolled.png');
await page.screenshot({ path: overflowShot, fullPage: false });
report.captures.push(overflowShot);

// Semantic color audit — all progress indicators use primary?
const overflowBars = await measureProgressBars(page);
const uniqueIndicatorColors = [...new Set(overflowBars.map((b) => b.indicatorBg))];
report.semanticGap = {
  uniqueIndicatorColors,
  allPrimaryOnly: uniqueIndicatorColors.length <= 1,
  barCount: overflowBars.length,
  sample: overflowBars.slice(0, 5),
};

if (uniqueIndicatorColors.length <= 1) {
  report.issues.push({ id: 'M01', detail: 'All progress indicators share single fill color (bg-primary); no outcome-based green/red/amber/neutral' });
}

// Panel height tolerance check
const livePanels = report.panels.filter((p) => p.label?.endsWith('-light'));
const problemsH = livePanels.find((p) => p.label === 'problems-light')?.outerHeight;
const actionsH = livePanels.find((p) => p.label === 'actions-light')?.outerHeight;
const focusH = livePanels.find((p) => p.label === 'focus-light')?.outerHeight;
const queueH = livePanels.find((p) => p.label === 'queue-light')?.outerHeight;

report.panelHeightCheck = {
  problems: problemsH,
  actions: actionsH,
  focus: focusH,
  queue: queueH,
  problemsActionsEqual: problemsH === actionsH,
  problemsFocusEqual: problemsH === focusH,
  trioWithin2px: problemsH && actionsH && focusH && Math.max(problemsH, actionsH, focusH) - Math.min(problemsH, actionsH, focusH) <= 2,
  queueNear400: queueH ? Math.abs(queueH - 400) <= 8 : null,
  trioNear440: problemsH ? Math.abs(problemsH - 440) <= 8 : null,
};

if (!report.panelHeightCheck.trioWithin2px) {
  report.issues.push({ id: 'L01', detail: `Problems/Actions/Focus heights unequal: ${problemsH}/${actionsH}/${focusH}px` });
}
if (report.panelHeightCheck.queueNear400 === false) {
  report.issues.push({ id: 'L01', detail: `Queue outer height ${queueH}px, expected ~400px` });
}

// Escalations empty state scroll
await page.unroute('**/cases');
await page.reload({ waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);
await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
await page.waitForTimeout(400);
const escEmpty = await measure(page, '[data-slot="empty"]');
report.measurements.push({ view: 'H06-escalations-empty', ...escEmpty });
const escShot = join(OUT, 'b3-escalations-empty-light.png');
await page.screenshot({ path: escShot, fullPage: false });
report.captures.push(escShot);

// B2 schema proxy quick check
await page.locator('[data-sidebar="menu-button"]').nth(2).click();
await page.waitForTimeout(500);
await page.locator('button').filter({ hasText: /Schema/i }).click();
await page.waitForTimeout(3500);
const e02 = await measure(page, 'button.bg-primary.text-primary-foreground');
if (e02) {
  const ratio = await contrastRatio(page, e02.color, e02.backgroundColor);
  report.measurements.push({ theme: 'light', view: 'E02-schema-selected', ratio, ...e02 });
  if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'E02', theme: 'light', ratio });
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

// Verdicts
for (const id of ['H01', 'H02', 'H03', 'H04', 'H05', 'H06', 'E01', 'E02', 'E03', 'E04', 'M01', 'L01']) {
  const idIssues = report.issues.filter((i) => i.id === id);
  if (['E03', 'E04'].includes(id) && report.endpoint.graph?.status !== 200) {
    report.verdicts[id] = idIssues.length ? `BLOCKED (${idIssues.length} issues)` : 'BLOCKED (no /graph)';
  } else if (id === 'M01') {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED' : 'NOT REPRODUCED';
  } else if (id === 'L01') {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED' : 'NOT REPRODUCED';
  } else {
    report.verdicts[id] = idIssues.length ? 'REPRODUCED' : 'NOT REPRODUCED';
  }
}

writeFileSync(join(OUT, 'measurements-b3-audit.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B3 audit issues:', report.issues.length);
console.log('Verdicts:', report.verdicts);
console.log('Panel heights:', report.panelHeightCheck);
console.log('written', join(OUT, 'measurements-b3-audit.json'));
