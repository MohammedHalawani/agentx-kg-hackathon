/**
 * Agent B (B3 Impl) — post-implementation evidence @ 1440×900
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

async function measure(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return {
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      className: el.className?.slice?.(0, 120) || '',
      height: Math.round(rect.height),
    };
  }, selector);
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  runId: '2026-09-17T19-21-agentx-ui-repair-proof',
  phase: 'b3-impl-after',
  agent: 'B',
  url: BASE,
  viewport: '1440x900',
  panels: [],
  progressSemantics: [],
  sticky: null,
  b1Sentinels: [],
  buildFingerprint: null,
};

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(800);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href.split('/').pop()),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src.split('/').pop()),
}));

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(800);

  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  if (countEl) {
    const ratio = await contrastRatio(page, countEl.color, theme === 'light' ? 'rgb(250, 249, 247)' : 'rgb(17, 19, 24)');
    report.b1Sentinels.push({ id: 'H01', theme, ratio });
  }

  await page.locator('[data-sidebar="menu-button"]').nth(1).click();
  await page.waitForTimeout(1000);

  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const sel = await measure(page, 'button.border-primary\\/30');
    if (sel) {
      const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
      report.b1Sentinels.push({ id: 'H03', theme, ratio });
    }
  }

  const queueRow = page.locator('tbody tr').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(150);
    const hover = await measure(page, 'tbody tr:hover');
    if (hover) {
      const ratio = await contrastRatio(page, hover.color, hover.backgroundColor);
      report.b1Sentinels.push({ id: 'H04', theme, ratio });
    }
  }
}

await setTheme(page, 'light');
await page.reload({ waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1000);

await page.screenshot({ path: join(OUT, 'b3-decisions-light-after.png'), fullPage: false });

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
  const sample = segments.slice(0, 6).map((el) => ({
    variant: el.getAttribute('data-variant'),
    bg: getComputedStyle(el).backgroundColor,
  }));
  return { segmentCount: segments.length, variants, primaryOnly, sample };
});

report.sticky = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const scrollOwner = card?.querySelector('.overflow-auto');
  const thead = card?.querySelector('thead.sticky');
  if (!scrollOwner || !thead) return { ok: false };

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

const focusSticky = await page.evaluate(() => {
  const thead = document.querySelector('thead.sticky');
  return thead ? getComputedStyle(thead).position : null;
});
report.focusStickyHeader = focusSticky;

writeFileSync(join(OUT, 'measurements-b3-after.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));

await browser.close();
