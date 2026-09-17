/**
 * Agent C (B3 Review) — independent verification @ 1440×900
 */
import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = __dirname;
const BASE = 'http://127.0.0.1:8000';

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t);
    const dark = t === 'dark';
    document.documentElement.classList.toggle('dark', dark);
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  }, theme);
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
  phase: 'b3-review',
  agent: 'C',
  url: BASE,
  viewport: '1440x900',
  apiMetrics: null,
  uiMetrics: null,
  panels: {},
  progressSemantics: {},
  queueSticky: null,
  focusSticky: null,
  queueScrollToEnd: null,
  b1Sentinels: [],
  buildFingerprint: null,
  issues: [],
};

// Fetch API metrics
const apiRes = await page.request.get(`${BASE}/cases`);
report.apiMetrics = await apiRes.json();

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href.split('/').pop()),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src.split('/').pop()),
}));

// Navigate to Decisions
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);

// UI metrics extraction
report.uiMetrics = await page.evaluate(() => {
  const text = document.body.innerText;
  const coveragePct = text.match(/(\d+)%\s*\n\s*of failure types/)?.[1];
  const openCases = text.match(/Open cases now\s*\n\s*(\d+)/)?.[1];
  const resolvedMatch = text.match(/(\d+)\s+resolved/);
  const openMatch = text.match(/(\d+)\s+open/);
  const historicalRate = [...document.querySelectorAll('.text-xl')].find((el) => el.textContent?.includes('%'))?.textContent;
  const precedentValue = [...document.querySelectorAll('.text-xl')].map((el) => el.textContent);
  return {
    coveragePct,
    resolvedText: resolvedMatch?.[1],
    openText: openMatch?.[1],
    historicalRate,
    allKpiValues: precedentValue,
  };
});

// Panel heights
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

// Progress semantics
report.progressSemantics = await page.evaluate(() => {
  const segments = [...document.querySelectorAll('[data-slot="segmented-progress-segment"]')];
  const variants = [...new Set(segments.map((s) => s.getAttribute('data-variant')))];
  const primaryOnly = document.querySelectorAll('[data-slot="progress-indicator"].bg-primary').length;
  const full100 = [];
  const partial80 = [];
  for (const btn of document.querySelectorAll('button')) {
    if (btn.textContent?.includes('100%')) {
      const segs = [...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant'));
      full100.push(segs);
    }
    if (btn.textContent?.includes('91%') || btn.textContent?.includes('90%')) {
      const segs = [...btn.querySelectorAll('[data-variant]')].map((s) => s.getAttribute('data-variant'));
      if (segs.length === 2) partial80.push(segs);
    }
  }
  const sample = segments.slice(0, 6).map((el) => ({
    variant: el.getAttribute('data-variant'),
    bg: getComputedStyle(el).backgroundColor,
  }));
  return { segmentCount: segments.length, variants, primaryOnly, full100, partial80, sample };
});

// Learning badge check
report.learningBadge = await page.evaluate(() => {
  const badges = [...document.querySelectorAll('[data-slot="badge"]')];
  const learningBadge = badges.find((b) => b.textContent?.includes('agent precedent') || b.textContent?.includes('No agent'));
  return learningBadge
    ? { text: learningBadge.textContent, className: learningBadge.className, hasChartGood: learningBadge.className.includes('text-chart-good') }
    : null;
});

// KPI tones
report.kpiTones = await page.evaluate(() => {
  const cards = [...document.querySelectorAll('[data-slot="card"]')];
  const result = {};
  for (const card of cards) {
    const label = card.querySelector('.text-muted-foreground')?.textContent?.trim();
    const icon = card.querySelector('.grid.size-8');
    if (label && icon) {
      result[label] = {
        hasGood: icon.className.includes('text-chart-good'),
        hasWarning: icon.className.includes('text-chart-warning'),
        hasPrimary: icon.className.includes('text-primary'),
      };
    }
  }
  return result;
});

// Queue sticky header test
report.queueSticky = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const scrollOwner = card?.querySelector('.overflow-auto');
  const thead = card?.querySelector('thead.sticky');
  if (!scrollOwner || !thead) return { ok: false, reason: 'missing elements' };

  const before = {
    ownerTop: scrollOwner.getBoundingClientRect().top,
    theadTop: thead.getBoundingClientRect().top,
  };
  scrollOwner.scrollTop = 400;
  const after = {
    scrollTop: scrollOwner.scrollTop,
    ownerTop: scrollOwner.getBoundingClientRect().top,
    theadTop: thead.getBoundingClientRect().top,
    theadPosition: getComputedStyle(thead).position,
  };
  return {
    ok: true,
    scrollOwner: 'overflow-auto',
    before,
    after,
    headerPinned: Math.abs(after.theadTop - after.ownerTop) < 4,
  };
});

// Queue scroll to row 75
report.queueScrollToEnd = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const scrollOwner = card?.querySelector('.overflow-auto');
  const rows = card?.querySelectorAll('tbody tr') ?? [];
  if (!scrollOwner || rows.length === 0) return { ok: false, rowCount: rows.length };

  scrollOwner.scrollTop = scrollOwner.scrollHeight;
  const lastRow = rows[rows.length - 1];
  const scrollRect = scrollOwner.getBoundingClientRect();
  const lastRect = lastRow.getBoundingClientRect();
  const visible = lastRect.top >= scrollRect.top && lastRect.bottom <= scrollRect.bottom + 2;

  return {
    ok: true,
    rowCount: rows.length,
    scrollTop: scrollOwner.scrollTop,
    scrollHeight: scrollOwner.scrollHeight,
    clientHeight: scrollOwner.clientHeight,
    lastRowVisible: visible,
    lastRowText: lastRow.textContent?.slice(0, 60),
  };
});

// Focus sticky header — select category with many matching cases
const categoryWithCases = report.apiMetrics.queue.reduce((acc, c) => {
  acc[c.category] = (acc[c.category] || 0) + 1;
  return acc;
}, {});
const bestCategory = Object.entries(categoryWithCases).sort((a, b) => b[1] - a[1])[0]?.[0];

if (bestCategory) {
  // Click problem row matching best category
  await page.locator('button').filter({ hasText: /%/ }).first().click();
  await page.waitForTimeout(300);

  // Find and click the category with most open cases in Problems panel
  const problemButtons = page.locator('button').filter({ has: page.locator('[data-slot="segmented-progress"]') });
  const count = await problemButtons.count();
  for (let i = 0; i < count; i++) {
    const btn = problemButtons.nth(i);
    await btn.click();
    await page.waitForTimeout(200);
    const matchingTable = await page.locator('thead.sticky').count();
    if (matchingTable >= 2) break;
  }

  report.focusSticky = await page.evaluate(() => {
    // Focus panel matching-cases table is the second sticky thead (queue is first)
    const focusCard = document.querySelector('.h-\\[440px\\].lg\\:col-span-2, .h-\\[440px\\].xl\\:col-span-1');
    const focusCards = [...document.querySelectorAll('.h-\\[440px\\]')];
    const focusPanel = focusCards.find((c) => c.textContent?.includes('Focus') || c.querySelector('[data-slot="card-title"]')?.textContent === 'Focus');
    if (!focusPanel) return { ok: false, reason: 'no focus panel' };

    const scrollArea = focusPanel.querySelector('[data-slot="scroll-area-viewport"]');
    const matchingSection = focusPanel.querySelector('thead.sticky');
    const matchingRows = focusPanel.querySelectorAll('tbody tr');

    if (!matchingSection || matchingRows.length === 0) {
      return {
        ok: false,
        reason: 'no matching cases table or empty',
        rowCount: matchingRows.length,
        hasScrollArea: !!scrollArea,
        theadPosition: matchingSection ? getComputedStyle(matchingSection).position : null,
      };
    }

    const scrollOwner = scrollArea || focusPanel.querySelector('.overflow-auto');
    if (!scrollOwner) return { ok: false, reason: 'no scroll owner' };

    const before = {
      ownerTop: scrollOwner.getBoundingClientRect().top,
      theadTop: matchingSection.getBoundingClientRect().top,
      scrollOwnerTag: scrollOwner.getAttribute('data-slot') || scrollOwner.className.slice(0, 40),
    };

    scrollOwner.scrollTop = scrollOwner.scrollHeight;
    const after = {
      scrollTop: scrollOwner.scrollTop,
      ownerTop: scrollOwner.getBoundingClientRect().top,
      theadTop: matchingSection.getBoundingClientRect().top,
      theadPosition: getComputedStyle(matchingSection).position,
      rowCount: matchingRows.length,
    };

    return {
      ok: true,
      before,
      after,
      headerPinned: Math.abs(after.theadTop - after.ownerTop) < 4,
      scrollOwnerType: scrollArea ? 'scroll-area-viewport' : 'overflow-auto',
    };
  });
}

// B1 sentinels
for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(800);
  await page.locator('[data-sidebar="menu-button"]').nth(1).click();
  await page.waitForTimeout(1000);

  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const sel = await page.evaluate(() => {
      const el = document.querySelector('button.border-primary\\/30');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { color: cs.color, backgroundColor: cs.backgroundColor };
    });
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.b1Sentinels.push({ id: 'H03', theme, ratio });
    }
  }

  const queueRow = page.locator('.h-\\[400px\\] tbody tr').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(150);
    const hover = await page.evaluate(() => {
      const el = document.querySelector('.h-\\[400px\\] tbody tr:hover') || document.querySelector('.h-\\[400px\\] tbody tr');
      if (!el) return null;
      const cs = getComputedStyle(el);
      return { color: cs.color, backgroundColor: cs.backgroundColor, selected: el.getAttribute('data-state') };
    });
    if (hover) {
      const ratio = await contrastRatio(page, hover.color, hover.backgroundColor);
      report.b1Sentinels.push({ id: 'H04', theme, ratio, selected: hover.selected });
    }
  }
}

// Metric comparison
const api = report.apiMetrics;
const totalCases = api.by_category.reduce((a, c) => a + c.cases, 0);
const totalWon = api.by_category.reduce((a, c) => a + c.succeeded, 0);
const expectedRate = totalCases ? Math.round((totalWon / totalCases) * 100) : 0;
const expectedCoveragePct = api.coverage.total ? Math.round((api.coverage.resolved / api.coverage.total) * 100) : 0;

report.metricComparison = {
  api: {
    coverage: api.coverage,
    writebacks: api.writebacks,
    overallRate: expectedRate,
    coveragePct: expectedCoveragePct,
    queueLength: api.queue.length,
  },
  expectedKpiTones: {
    openCases: api.coverage.unresolved > 0 ? 'warning' : 'good',
    precedent:
      api.coverage.resolved > 0 && api.coverage.unresolved === 0
        ? 'good'
        : api.coverage.unresolved > 0
          ? 'warning'
          : 'default',
  },
};

await page.screenshot({ path: join(OUT, 'b3-decisions-light-review.png'), fullPage: false });

writeFileSync(join(OUT, 'measurements-b3-review.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

await browser.close();
