/**
 * Agent D (B3 Gate) — independent commit-readiness verification @ 1440×900
 * Candidate build: index-DVhlRZ8U.css / index-BVWhf3oi.js
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const CANDIDATE_CSS = 'index-DVhlRZ8U.css';
const CANDIDATE_JS = 'index-BVWhf3oi.js';
const SHOT = (name) => join(OUT, `${name}-gate.png`);

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
}

async function setThemeViaUI(page, theme) {
  const label = theme === 'dark' ? 'Dark' : theme === 'light' ? 'Light' : 'System';
  await page.locator('button[aria-label*="theme" i], button[aria-label*="Theme" i]').first().click();
  await page.waitForTimeout(200);
  await page.getByRole('menuitem', { name: label }).click();
  await page.waitForTimeout(500);
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

async function measure(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { color: cs.color, backgroundColor: cs.backgroundColor, className: el.className };
  }, selector);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  runId: '2026-09-17T19-21-agentx-ui-repair-proof',
  phase: 'b3-gate',
  agent: 'D',
  url: BASE,
  viewport: '1440x900',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  apiMetrics: null,
  uiMetrics: null,
  panels: {},
  progressSemantics: {},
  progressSemanticsDark: null,
  selectedRowBars: null,
  queueSticky: null,
  focusSticky: null,
  queueScrollToEnd: null,
  focusLastCase: null,
  overflowFixture: null,
  b1Sentinels: [],
  b2SchemaSmoke: null,
  buildFingerprint: null,
  metricComparison: null,
  issues: [],
  captures: [],
};

const apiRes = await page.request.get(`${BASE}/cases`);
report.apiMetrics = await apiRes.json();

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href.split('/').pop()),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src.split('/').pop()),
}));

const servedCss = report.buildFingerprint.css.find((h) => h?.includes('index-') && h.endsWith('.css'));
const servedJs = report.buildFingerprint.js.find((h) => h?.includes('index-') && h.endsWith('.js'));
if (!servedCss?.includes(CANDIDATE_CSS) || !servedJs?.includes(CANDIDATE_JS)) {
  report.issues.push({
    id: 'BUILD',
    severity: 'BLOCKER',
    detail: `Served assets mismatch. Expected ${CANDIDATE_CSS}/${CANDIDATE_JS}, got ${servedCss}/${servedJs}`,
  });
}

await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);

report.uiMetrics = await page.evaluate(() => {
  const resolvedMatch = document.body.innerText.match(/(\d+)\s+resolved/);
  const openMatch = document.body.innerText.match(/(\d+)\s+open/);
  const historicalRate = [...document.querySelectorAll('.text-xl')].find((el) => el.textContent?.includes('%'))?.textContent;
  return {
    resolvedText: resolvedMatch?.[1],
    openText: openMatch?.[1],
    historicalRate,
    allKpiValues: [...document.querySelectorAll('.text-xl')].map((el) => el.textContent),
  };
});

report.panels = await page.evaluate(() => {
  const heights = {};
  for (const el of document.querySelectorAll('.h-\\[440px\\]')) {
    const title = el.querySelector('[data-slot="card-title"]')?.textContent?.trim();
    heights[title || 'unknown-440'] = Math.round(el.getBoundingClientRect().height);
  }
  const queue = document.querySelector('.h-\\[400px\\]');
  heights.queue = queue ? Math.round(queue.getBoundingClientRect().height) : null;
  return heights;
});

report.progressSemantics = await page.evaluate(() => {
  const segments = [...document.querySelectorAll('[data-slot="segmented-progress-segment"]')];
  const variants = [...new Set(segments.map((s) => s.getAttribute('data-variant')))];
  const primaryOnly = document.querySelectorAll('[data-slot="progress-indicator"].bg-primary').length;
  const full100 = [];
  const partial80 = [];
  for (const btn of document.querySelectorAll('button')) {
    if (btn.textContent?.includes('100%')) {
      full100.push([...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant')));
    }
    if (btn.textContent?.includes('91%') || btn.textContent?.includes('80%')) {
      const segs = [...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant'));
      if (segs.length === 2) partial80.push(segs);
    }
  }
  const sample = segments.slice(0, 6).map((el) => ({
    variant: el.getAttribute('data-variant'),
    bg: getComputedStyle(el).backgroundColor,
    className: el.className,
  }));
  return { segmentCount: segments.length, variants, primaryOnly, full100, partial80, sample };
});

if (report.progressSemantics.primaryOnly > 0) {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'bg-primary indicators still present' });
}
if (!report.progressSemantics.variants.includes('success')) {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'No success variant segments found' });
}

// Selected row bars not turned blue
const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
if (await problemRow.count()) {
  await problemRow.click();
  await page.waitForTimeout(200);
}
report.selectedRowBars = await page.evaluate(() => {
  const selectedBtn = document.querySelector('button.border-primary\\/30, button.bg-accent');
  if (!selectedBtn) return { ok: false, reason: 'no selected row' };
  const segments = [...selectedBtn.querySelectorAll('[data-slot="segmented-progress-segment"]')];
  const details = segments.map((s) => ({
    variant: s.getAttribute('data-variant'),
    bg: getComputedStyle(s).backgroundColor,
    hasPrimary: s.className.includes('bg-primary'),
    hasOutcome: /bg-outcome-/.test(s.className),
  }));
  const primaryBlue = details.filter((d) => d.hasPrimary || d.bg.includes('87, 117, 245'));
  return {
    ok: primaryBlue.length === 0 && details.some((d) => d.hasOutcome || d.variant === 'success' || d.variant === 'failure'),
    segmentCount: details.length,
    details,
    rowBg: getComputedStyle(selectedBtn).backgroundColor,
  };
});
if (report.selectedRowBars.ok === false && report.selectedRowBars.reason !== 'no selected row') {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'Selected row progress bars turned primary blue' });
}

report.queueSticky = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const scrollOwner = card?.querySelector('.overflow-auto');
  const thead = card?.querySelector('thead.sticky');
  if (!scrollOwner || !thead) return { ok: false, reason: 'missing elements' };
  const before = { ownerTop: scrollOwner.getBoundingClientRect().top, theadTop: thead.getBoundingClientRect().top };
  scrollOwner.scrollTop = 400;
  const after = {
    scrollTop: scrollOwner.scrollTop,
    ownerTop: scrollOwner.getBoundingClientRect().top,
    theadTop: thead.getBoundingClientRect().top,
    theadPosition: getComputedStyle(thead).position,
  };
  return { ok: true, scrollOwner: 'overflow-auto', before, after, headerPinned: Math.abs(after.theadTop - after.ownerTop) < 4 };
});
if (!report.queueSticky.headerPinned) {
  report.issues.push({ id: 'L02', severity: 'HIGH', detail: 'Queue sticky header not pinned' });
}

report.queueScrollToEnd = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const scrollOwner = card?.querySelector('.overflow-auto');
  const rows = card?.querySelectorAll('tbody tr') ?? [];
  if (!scrollOwner || rows.length === 0) return { ok: false, rowCount: rows.length };
  scrollOwner.scrollTop = scrollOwner.scrollHeight;
  const lastRow = rows[rows.length - 1];
  const scrollRect = scrollOwner.getBoundingClientRect();
  const lastRect = lastRow.getBoundingClientRect();
  return {
    ok: true,
    rowCount: rows.length,
    scrollTop: scrollOwner.scrollTop,
    scrollHeight: scrollOwner.scrollHeight,
    clientHeight: scrollOwner.clientHeight,
    lastRowVisible: lastRect.top >= scrollRect.top && lastRect.bottom <= scrollRect.bottom + 2,
    lastRowText: lastRow.textContent?.slice(0, 80),
    lastFailureId: lastRow.querySelector('td')?.textContent?.trim(),
  };
});
if (!report.queueScrollToEnd.lastRowVisible) {
  report.issues.push({ id: 'L01', severity: 'HIGH', detail: 'Queue row 75 not visible after scroll' });
}

// Focus panel — select category with most matching cases, scroll to last
const categoryCounts = report.apiMetrics.queue.reduce((acc, c) => {
  acc[c.category] = (acc[c.category] || 0) + 1;
  return acc;
}, {});
const bestCategory = Object.entries(categoryCounts).sort((a, b) => b[1] - a[1])[0]?.[0];
if (bestCategory) {
  const problemButtons = page.locator('button').filter({ has: page.locator('[data-slot="segmented-progress"]') });
  const count = await problemButtons.count();
  for (let i = 0; i < count; i++) {
    const btn = problemButtons.nth(i);
    const text = await btn.textContent();
    if (text?.includes(bestCategory.replace(/_/g, ' ')) || text?.includes(bestCategory)) {
      await btn.click();
      break;
    }
  }
  await page.waitForTimeout(400);

  report.focusSticky = await page.evaluate(() => {
    const focusCards = [...document.querySelectorAll('.h-\\[440px\\]')];
    const focusPanel = focusCards.find((c) => c.querySelector('[data-slot="card-title"]')?.textContent === 'Focus');
    if (!focusPanel) return { ok: false, reason: 'no focus panel' };
    const scrollArea = focusPanel.querySelector('[data-slot="scroll-area-viewport"]');
    const matchingSection = focusPanel.querySelector('thead.sticky');
    const matchingRows = focusPanel.querySelectorAll('tbody tr');
    if (!matchingSection || matchingRows.length === 0) return { ok: false, reason: 'no matching cases', rowCount: matchingRows.length };
    const scrollOwner = scrollArea || focusPanel.querySelector('.overflow-auto');
    const before = { ownerTop: scrollOwner.getBoundingClientRect().top, theadTop: matchingSection.getBoundingClientRect().top };
    scrollOwner.scrollTop = scrollOwner.scrollHeight;
    const after = {
      scrollTop: scrollOwner.scrollTop,
      ownerTop: scrollOwner.getBoundingClientRect().top,
      theadTop: matchingSection.getBoundingClientRect().top,
      rowCount: matchingRows.length,
    };
    const lastRow = matchingRows[matchingRows.length - 1];
    const scrollRect = scrollOwner.getBoundingClientRect();
    const lastRect = lastRow.getBoundingClientRect();
    return {
      ok: true,
      before,
      after,
      headerPinned: Math.abs(after.theadTop - after.ownerTop) < 4,
      lastRowVisible: lastRect.top >= scrollRect.top && lastRect.bottom <= scrollRect.bottom + 4,
      lastRowText: lastRow.textContent?.slice(0, 60),
    };
  });
  if (!report.focusSticky?.headerPinned) {
    report.issues.push({ id: 'L03', severity: 'HIGH', detail: 'Focus sticky header not pinned' });
  }
  report.focusLastCase = {
    category: bestCategory,
    ...report.focusSticky,
  };
}

// Dark theme semantic colors
await setTheme(page, 'dark');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);

report.progressSemanticsDark = await page.evaluate(() => {
  const segments = [...document.querySelectorAll('[data-slot="segmented-progress-segment"]')];
  const variants = [...new Set(segments.map((s) => s.getAttribute('data-variant')))];
  const sample = segments.slice(0, 6).map((el) => ({
    variant: el.getAttribute('data-variant'),
    bg: getComputedStyle(el).backgroundColor,
  }));
  const visible = sample.filter((s) => s.bg && s.bg !== 'rgba(0, 0, 0, 0)');
  return { segmentCount: segments.length, variants, sample, visibleCount: visible.length };
});
if (report.progressSemanticsDark.visibleCount === 0) {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'Dark theme semantic bar colors not visible' });
}

const darkShot = SHOT('b3-decisions-dark');
await page.screenshot({ path: darkShot, fullPage: false });
report.captures.push(darkShot);

// Light screenshot
await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);
const lightShot = SHOT('b3-decisions-light');
await page.screenshot({ path: lightShot, fullPage: false });
report.captures.push(lightShot);

// B1 sentinels H03/H04
for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.locator('[data-sidebar="menu-button"]').nth(1).click();
  await page.waitForTimeout(1000);

  const prob = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await prob.count()) {
    await prob.click();
    await page.waitForTimeout(200);
    const sel = await measure(page, 'button.border-primary\\/30, button.bg-accent');
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.b1Sentinels.push({ id: 'H03', theme, ratio, pass: ratio >= 4.5 });
      if (ratio < 4.5) report.issues.push({ id: 'H03', severity: 'HIGH', theme, ratio });
    }
  }

  const queueRow = page.locator('.h-\\[400px\\] tbody tr').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(150);
    const hover = await page.evaluate(() => {
      const el = document.querySelector('.h-\\[400px\\] tbody tr');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { color: cs.color, backgroundColor: cs.backgroundColor };
    });
    if (hover) {
      const ratio = await contrastRatio(page, hover.color, hover.backgroundColor);
      report.b1Sentinels.push({ id: 'H04', theme, ratio, pass: ratio >= 4.5 });
      if (ratio < 4.5) report.issues.push({ id: 'H04', severity: 'HIGH', theme, ratio });
    }
  }
}

// B2 schema proxy smoke
await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(800);
await page.locator('[data-sidebar="menu-button"]').nth(2).click();
await page.waitForTimeout(500);
await page.locator('button').filter({ hasText: /Schema/i }).click();
await page.waitForTimeout(3500);

const readGraphSurface = async () =>
  page.evaluate(() => {
    const wrap = document.querySelector('.relative.h-full.w-full.overflow-hidden.bg-surface');
    return {
      wrapBg: wrap ? getComputedStyle(wrap).backgroundColor : null,
      surfaceVar: getComputedStyle(document.documentElement).getPropertyValue('--color-surface').trim(),
    };
  });

await setThemeViaUI(page, 'light');
const light2d = await readGraphSurface();
await setThemeViaUI(page, 'dark');
const dark2d = await readGraphSurface();
report.b2SchemaSmoke = {
  light: light2d,
  dark: dark2d,
  wrapChanged: light2d.wrapBg !== dark2d.wrapBg,
  surfaceChanged: light2d.surfaceVar !== dark2d.surfaceVar,
  pass: light2d.wrapBg !== dark2d.wrapBg,
};
if (!report.b2SchemaSmoke.pass) {
  report.issues.push({ id: 'E02', severity: 'HIGH', detail: 'Schema 2D wrap unchanged on theme toggle' });
}

const schemaShot = SHOT('b3-schema-dark');
await page.screenshot({ path: schemaShot, fullPage: false });
report.captures.push(schemaShot);

// Overflow fixture
const overflowFixture = {
  ...report.apiMetrics,
  by_category: Array.from({ length: 30 }, (_, i) => ({
    category: `overflow_cat_${i}`,
    cases: 10 + i,
    succeeded: 5 + i,
    success_rate: 50 + i,
  })),
  by_action: Array.from({ length: 20 }, (_, i) => ({
    action: `Overflow action ${i} with a long label to test wrapping and scroll`,
    used: 20 - i,
    succeeded: 10,
    success_rate: 50,
  })),
  queue: Array.from({ length: 80 }, (_, i) => ({
    failure_id: `FR-overflow-${String(i).padStart(4, '0')}`,
    category: `overflow_cat_${i % 30}`,
    description: `Overflow queue row ${i}`,
    city: `City ${i}`,
    district: `District ${i}`,
    courier: `Courier ${i}`,
    shipment_id: `SHP-OVR-${String(i).padStart(4, '0')}`,
  })),
};

await page.route('**/cases', (route) => {
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overflowFixture) });
});
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1500);
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1200);

report.overflowFixture = await page.evaluate(() => {
  const panels = {};
  for (const el of document.querySelectorAll('.h-\\[440px\\]')) {
    const title = el.querySelector('[data-slot="card-title"]')?.textContent?.trim();
    panels[title || 'unknown'] = Math.round(el.getBoundingClientRect().height);
  }
  const queueCard = document.querySelector('.h-\\[400px\\]');
  panels.queue = queueCard ? Math.round(queueCard.getBoundingClientRect().height) : null;

  const scrollReach = {};
  for (const [key, re] of [
    ['problems', /Problems/i],
    ['actions', /Actions/i],
    ['queue', /Open cases|Queue/i],
  ]) {
    const card = [...document.querySelectorAll('[data-slot="card"]')].find((c) => re.test(c.textContent || ''));
    const owner = card?.querySelector('.overflow-auto, [data-slot="scroll-area-viewport"]');
    if (owner) {
      owner.scrollTop = owner.scrollHeight;
      scrollReach[key] = {
        scrollHeight: owner.scrollHeight,
        clientHeight: owner.clientHeight,
        overflow: owner.scrollHeight > owner.clientHeight,
        reachedEnd: owner.scrollTop >= owner.scrollHeight - owner.clientHeight - 2,
      };
    }
  }
  const problemCount = document.querySelectorAll('button [data-slot="segmented-progress"]').length;
  const queueRows = document.querySelectorAll('.h-\\[400px\\] tbody tr').length;
  return { panels, scrollReach, problemBarCount: problemCount, queueRowCount: queueRows };
});

if (report.overflowFixture.problemBarCount < 20) {
  report.issues.push({ id: 'L01', severity: 'MEDIUM', detail: `Overflow fixture problems count ${report.overflowFixture.problemBarCount} < 20` });
}
if (report.overflowFixture.queueRowCount < 75) {
  report.issues.push({ id: 'L01', severity: 'MEDIUM', detail: `Overflow fixture queue rows ${report.overflowFixture.queueRowCount} < 75` });
}

const overflowShot = SHOT('b3-decisions-overflow');
await page.screenshot({ path: overflowShot, fullPage: false });
report.captures.push(overflowShot);

// Metric comparison
const api = report.apiMetrics;
const totalCases = api.by_category.reduce((a, c) => a + c.cases, 0);
const totalWon = api.by_category.reduce((a, c) => a + c.succeeded, 0);
report.metricComparison = {
  api: {
    coverage: api.coverage,
    writebacks: api.writebacks,
    overallRate: totalCases ? Math.round((totalWon / totalCases) * 100) : 0,
    coveragePct: api.coverage.total ? Math.round((api.coverage.resolved / api.coverage.total) * 100) : 0,
    queueLength: api.queue.length,
  },
  ui: {
    resolved: report.uiMetrics.resolvedText,
    open: report.uiMetrics.openText,
    historicalRate: report.uiMetrics.historicalRate,
  },
  matches: {
    resolved: String(api.coverage.resolved) === report.uiMetrics.resolvedText,
    open: String(api.coverage.unresolved) === report.uiMetrics.openText,
    historicalRate: report.uiMetrics.historicalRate === `${totalCases ? Math.round((totalWon / totalCases) * 100) : 0}%`,
    queueLength: report.queueScrollToEnd.rowCount === api.queue.length,
  },
};

for (const [k, v] of Object.entries(report.metricComparison.matches)) {
  if (!v) report.issues.push({ id: 'DATA', severity: 'HIGH', detail: `API/UI mismatch: ${k}` });
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

report.panelHeightCheck = {
  problems: report.panels.Problems,
  actions: report.panels['Resolution actions'],
  focus: report.panels.Focus,
  queue: report.panels.queue,
  pass:
    report.panels.Problems === 440 &&
    report.panels['Resolution actions'] === 440 &&
    report.panels.Focus === 440 &&
    report.panels.queue === 400,
};

if (!report.panelHeightCheck.pass) {
  report.issues.push({ id: 'L01', severity: 'HIGH', detail: `Panel heights: ${JSON.stringify(report.panels)}` });
}

report.learningBadge = await page.unroute('**/cases').then(() =>
  page.evaluate(() => {
    const badge = [...document.querySelectorAll('[data-slot="badge"]')].find(
      (b) => b.textContent?.includes('agent') || b.textContent?.includes('No agent'),
    );
    return badge ? { text: badge.textContent, hasChartGood: badge.className.includes('text-chart-good') } : null;
  }),
);

writeFileSync(join(OUT, 'measurements-b3-gate.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B3 gate issues:', report.issues.length, report.issues);
console.log('Metric matches:', report.metricComparison.matches);
console.log('B1 sentinels:', report.b1Sentinels);
console.log('written', join(OUT, 'measurements-b3-gate.json'));
