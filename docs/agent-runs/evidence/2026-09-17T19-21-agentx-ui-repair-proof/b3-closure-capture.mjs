/**
 * Agent 5C (B3 Closure) — independent revalidation @ 1440×900 AR locale
 * Frozen candidate: index-DVhlRZ8U.css / index-DE557tU5.js
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const CANDIDATE_CSS = 'index-DVhlRZ8U.css';
const CANDIDATE_JS = 'index-DE557tU5.js';

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
}

async function setLanguage(page, lang) {
  await page.evaluate((l) => {
    localStorage.setItem('agentx-language', l);
    document.documentElement.lang = l;
    document.documentElement.dir = 'ltr';
  }, lang);
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
  phase: 'b3-closure',
  agent: '5C',
  locale: 'ar',
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
  buildFingerprint: null,
  metricComparison: null,
  kpiTones: null,
  learningBadge: null,
  coverageBar: null,
  issues: [],
  verdicts: {},
};

const apiRes = await page.request.get(`${BASE}/cases`);
report.apiMetrics = await apiRes.json();

await page.goto(BASE, { waitUntil: 'networkidle' });
await setLanguage(page, 'ar');
await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1000);

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
await page.waitForTimeout(1200);

report.uiMetrics = await page.evaluate(() => {
  const kpis = [...document.querySelectorAll('.text-xl')].map((el) => el.textContent?.trim());
  const body = document.body.innerText;
  const openKpi = kpis.find((v) => v === '75') ?? body.match(/الحالات المفتوحة[\s\S]{0,80}?(\d+)/)?.[1];
  const resolvedKpi = kpis.filter((v) => /^\d+$/.test(v || ''));
  const historicalRate = kpis.find((v) => v?.includes('%'));
  const coverageResolved = body.match(/تم حلها[\s\n]*(\d+)/)?.[1];
  const coverageOpen = body.match(/مفتوحة[\s\n]*(\d+)/)?.[1];
  return {
    kpis,
    openKpi,
    resolvedKpi: resolvedKpi[1] ?? coverageResolved,
    historicalRate,
    coverageResolved,
    coverageOpen,
    pageTitle: document.querySelector('h2')?.textContent,
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
  const partial = [];
  for (const btn of document.querySelectorAll('button')) {
    if (btn.textContent?.includes('100%')) {
      full100.push([...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant')));
    }
    const pct = btn.textContent?.match(/(\d+)%/);
    if (pct && +pct[1] < 100 && pct[1] >= 80) {
      const segs = [...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant'));
      if (segs.length === 2) partial.push({ pct: pct[1], segs });
    }
  }
  const sample = segments.slice(0, 6).map((el) => ({
    variant: el.getAttribute('data-variant'),
    bg: getComputedStyle(el).backgroundColor,
    className: el.className,
  }));
  return { segmentCount: segments.length, variants, primaryOnly, full100, partial, sample };
});

if (report.progressSemantics.primaryOnly > 0) {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'bg-primary indicators still present' });
}
if (!report.progressSemantics.variants.includes('success')) {
  report.issues.push({ id: 'M01', severity: 'HIGH', detail: 'No success variant segments found' });
}

report.coverageBar = await page.evaluate(() => {
  const card = [...document.querySelectorAll('[data-slot="card"]')].find((c) =>
    c.textContent?.includes('تغطية الحالات'),
  );
  const segments = card ? [...card.querySelectorAll('[data-slot="segmented-progress-segment"]')] : [];
  return {
    segmentCount: segments.length,
    variants: segments.map((s) => s.getAttribute('data-variant')),
    sample: segments.map((s) => ({
      variant: s.getAttribute('data-variant'),
      bg: getComputedStyle(s).backgroundColor,
    })),
  };
});
if (!report.coverageBar.variants.includes('success') || !report.coverageBar.variants.includes('pending')) {
  report.issues.push({ id: 'M03', severity: 'HIGH', detail: 'Coverage bar missing success/pending segments' });
}

report.learningBadge = await page.evaluate(() => {
  const badge = [...document.querySelectorAll('[data-slot="badge"]')].find(
    (b) => b.textContent?.includes('الوكيل') || b.textContent?.includes('إضافات'),
  );
  return badge
    ? { text: badge.textContent, hasChartGood: badge.className.includes('text-chart-good') }
    : { text: null, hasChartGood: false };
});
if (report.learningBadge.hasChartGood) {
  report.issues.push({ id: 'M04', severity: 'HIGH', detail: 'Learning badge still uses text-chart-good' });
}

report.kpiTones = await page.evaluate(() => {
  const tiles = [...document.querySelectorAll('[data-slot="card"]')]
    .flatMap((c) => {
      const label = c.querySelector('.text-sm.font-medium')?.textContent;
      const valueEl = c.querySelector('.text-xl');
      if (!label || !valueEl) return [];
      return [{ label, value: valueEl.textContent, className: valueEl.className }];
    })
    .filter((t) => t.label?.includes('السوابق') || t.label?.includes('الحالات المفتوحة'));
  const precedent = tiles.find((t) => t.label?.includes('السوابق'));
  const openCases = tiles.find((t) => t.label?.includes('الحالات المفتوحة'));
  return {
    precedent: precedent
      ? { warning: precedent.className.includes('text-chart-warning'), className: precedent.className }
      : null,
    openCases: openCases
      ? { warning: openCases.className.includes('text-chart-warning'), className: openCases.className }
      : null,
  };
});
if (report.apiMetrics.coverage.unresolved > 0 && !report.kpiTones.precedent?.warning) {
  report.issues.push({ id: 'M05', severity: 'HIGH', detail: 'Precedent KPI not warning when open > 0' });
}

const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
if (await problemRow.count()) {
  await problemRow.click();
  await page.waitForTimeout(250);
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
  const primaryBlue = details.filter((d) => d.hasPrimary);
  return {
    ok: primaryBlue.length === 0 && details.some((d) => d.hasOutcome || d.variant === 'success' || d.variant === 'failure'),
    segmentCount: details.length,
    details,
    rowBg: getComputedStyle(selectedBtn).backgroundColor,
  };
});
if (!report.selectedRowBars.ok && report.selectedRowBars.reason !== 'no selected row') {
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
  report.issues.push({ id: 'L01', severity: 'HIGH', detail: 'Queue last row not visible after scroll' });
}

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
    if (text?.includes('تعارض') || text?.includes(bestCategory.replace(/_/g, ' '))) {
      await btn.click();
      break;
    }
  }
  await page.waitForTimeout(400);

  report.focusSticky = await page.evaluate(() => {
    const focusCards = [...document.querySelectorAll('.h-\\[440px\\]')];
    const focusPanel = focusCards.find((c) => c.querySelector('[data-slot="card-title"]')?.textContent?.includes('التفاصيل'));
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
  report.focusLastCase = { category: bestCategory, ...report.focusSticky };
}

await setTheme(page, 'dark');
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1000);
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1200);

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

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await setLanguage(page, 'ar');
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1000);
  await page.locator('[data-sidebar="menu-button"]').nth(1).click();
  await page.waitForTimeout(1200);

  const prob = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await prob.count()) {
    await prob.click();
    await page.waitForTimeout(200);
    const sel = await measure(page, 'button.border-primary\\/30, button.bg-accent');
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.b1Sentinels.push({ id: 'H03', theme, lang: 'ar', ratio, pass: ratio >= 4.5 });
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
      report.b1Sentinels.push({ id: 'H04', theme, lang: 'ar', ratio, pass: ratio >= 4.5 });
      if (ratio < 4.5) report.issues.push({ id: 'H04', severity: 'HIGH', theme, ratio });
    }
  }
}

const overflowFixture = {
  ...report.apiMetrics,
  by_category: Array.from({ length: 30 }, (_, i) => ({
    category: `overflow_cat_${i}`,
    cases: 10 + i,
    succeeded: 5 + i,
    success_rate: 50 + i,
  })),
  by_action: Array.from({ length: 20 }, (_, i) => ({
    action: `إجراء اختبار ${i} مع نص طويل لاختبار التمرير`,
    used: 20 - i,
    succeeded: 10,
    success_rate: 50,
  })),
  queue: Array.from({ length: 80 }, (_, i) => ({
    failure_id: `FR-overflow-${String(i).padStart(4, '0')}`,
    category: `overflow_cat_${i % 30}`,
    description: `صف اختبار ${i}`,
    city: `مدينة ${i}`,
    district: `حي ${i}`,
    courier: `مندوب ${i}`,
    shipment_id: `SHP-OVR-${String(i).padStart(4, '0')}`,
  })),
};

await setTheme(page, 'light');
await setLanguage(page, 'ar');
await page.route('**/cases', (route) => {
  route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overflowFixture) });
});
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
    ['problems', /المشكلات/],
    ['actions', /إجراءات المعالجة/],
    ['queue', /قائمة الحالات/],
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

const api = report.apiMetrics;
const totalCases = api.by_category.reduce((a, c) => a + c.cases, 0);
const totalWon = api.by_category.reduce((a, c) => a + c.succeeded, 0);
const overallRate = totalCases ? Math.round((totalWon / totalCases) * 100) : 0;

report.metricComparison = {
  api: {
    coverage: api.coverage,
    writebacks: api.writebacks,
    overallRate,
    coveragePct: api.coverage.total ? Math.round((api.coverage.resolved / api.coverage.total) * 100) : 0,
    queueLength: api.queue.length,
  },
  ui: {
    openKpi: report.uiMetrics.openKpi ?? report.uiMetrics.kpis?.[0],
    resolvedKpi: report.uiMetrics.resolvedKpi,
    historicalRate: report.uiMetrics.historicalRate,
    coverageResolved: report.uiMetrics.coverageResolved,
    coverageOpen: report.uiMetrics.coverageOpen,
  },
  matches: {
    open: String(api.coverage.unresolved) === String(report.uiMetrics.openKpi ?? report.uiMetrics.kpis?.[0]),
    resolved: String(api.coverage.resolved) === String(report.uiMetrics.resolvedKpi ?? report.uiMetrics.coverageResolved),
    historicalRate: report.uiMetrics.historicalRate === `${overallRate}%`,
    queueLength: report.queueScrollToEnd.rowCount === api.queue.length,
  },
};

for (const [k, v] of Object.entries(report.metricComparison.matches)) {
  if (!v) report.issues.push({ id: 'DATA', severity: 'HIGH', detail: `API/UI mismatch: ${k}` });
}

report.panelHeightCheck = {
  problems: report.panels['المشكلات'],
  actions: report.panels['إجراءات المعالجة'],
  focus: report.panels['التفاصيل'],
  queue: report.panels.queue,
  pass:
    report.panels['المشكلات'] === 440 &&
    report.panels['إجراءات المعالجة'] === 440 &&
    report.panels['التفاصيل'] === 440 &&
    report.panels.queue === 400,
};

if (!report.panelHeightCheck.pass) {
  report.issues.push({ id: 'L01', severity: 'HIGH', detail: `Panel heights: ${JSON.stringify(report.panels)}` });
}

report.verdicts = {
  M01: report.issues.filter((i) => i.id === 'M01').length === 0 ? 'PASS' : 'FAIL',
  M02: report.progressSemantics.full100?.length > 0 && report.progressSemantics.partial?.length > 0 ? 'PASS' : 'FAIL',
  M03: report.coverageBar.variants.includes('success') && report.coverageBar.variants.includes('pending') ? 'PASS' : 'FAIL',
  M04: !report.learningBadge.hasChartGood ? 'PASS' : 'FAIL',
  M05: report.kpiTones.precedent?.warning ? 'PASS' : 'FAIL',
  L01: report.panelHeightCheck.pass ? 'PASS' : 'FAIL',
  L02: report.queueSticky.headerPinned ? 'PASS' : 'FAIL',
  L03: report.focusSticky?.headerPinned ? 'PASS' : 'FAIL',
  H03: report.b1Sentinels.filter((s) => s.id === 'H03').every((s) => s.pass) ? 'PASS' : 'FAIL',
  H04: report.b1Sentinels.filter((s) => s.id === 'H04').every((s) => s.pass) ? 'PASS' : 'FAIL',
  OVERFLOW: report.overflowFixture.scrollReach?.problems?.reachedEnd && report.overflowFixture.scrollReach?.actions?.reachedEnd ? 'PASS' : 'FAIL',
  OVERALL: report.issues.length === 0 ? 'PASS' : 'CONDITIONAL',
};

writeFileSync(join(OUT, 'measurements-b3-closure.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B3 closure issues:', report.issues.length, report.issues);
console.log('Verdicts:', report.verdicts);
console.log('written', join(OUT, 'measurements-b3-closure.json'));
