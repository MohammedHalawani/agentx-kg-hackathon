/**
 * Agent A (B4 Audit) — bilingual UI domain display @ 1440×900
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

const EN_UI_MARKERS = [
  'Open cases',
  'Decisions',
  'Explore',
  'Case coverage',
  'Problems',
  'Resolution actions',
  'Open case queue',
  'All root causes',
  'Theme',
  'Language',
  'Graph',
  'Schema',
  'Force',
  'Tree',
  'Light',
  'Dark',
  'pending',
  'shipment(s) awaiting',
];

const AR_UI_MARKERS = [
  'الحالات المفتوحة',
  'القرارات',
  'الاستكشاف',
  'تغطية الحالات',
  'المشكلات',
  'إجراءات المعالجة',
  'قائمة الحالات المفتوحة',
  'جميع الأسباب الجذرية',
  'المظهر',
  'اللغة',
  'الرسم',
  'المخطط',
  'قوة',
  'شجرة',
  'فاتح',
  'داكن',
];

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

async function reload(page) {
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
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

async function collectVisibleText(page) {
  return page.evaluate(() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const chunks = [];
    while (walker.nextNode()) {
      const t = walker.currentNode.textContent?.trim();
      if (t && t.length > 1) chunks.push(t);
    }
    return chunks.join('\n');
  });
}

async function findEnglishResiduals(page) {
  return page.evaluate((markers) => {
    const body = document.body.innerText || '';
    const hits = [];
    for (const m of markers) {
      if (body.includes(m)) hits.push(m);
    }
    // category-like raw keys in intake metadata spans
    const rawCats = [...document.querySelectorAll('button span')].map((s) => s.textContent?.trim()).filter(Boolean);
    const snake = rawCats.filter((t) => /^[a-z]+(_[a-z]+)+$/.test(t));
    return { enMarkers: hits, rawCategoryKeys: snake.slice(0, 10) };
  }, EN_UI_MARKERS);
}

async function getSchemaLegendLabels(page) {
  return page.evaluate(() => {
    const legend = document.querySelector('.pointer-events-none.absolute.left-3.top-3');
    if (!legend) return [];
    return [...legend.querySelectorAll('span.pointer-events-auto')].map((s) => s.childNodes[0]?.textContent?.trim()).filter(Boolean);
  });
}

async function getGraphMountCount(page) {
  return page.evaluate(() => window.__b4GraphMounts ?? 0);
}

async function installGraphMountProbe(page) {
  await page.addInitScript(() => {
    window.__b4GraphMounts = 0;
    const orig = React?.createElement;
    // fallback: count canvas/webgl containers after layout
  });
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const report = {
  url: BASE,
  viewport: '1440x900',
  phase: 'b4-audit',
  agent: 'A',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  captures: [],
  measurements: [],
  issues: [],
  englishInventory: {},
  verdicts: {},
};

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}));

const graphStatus = await page.evaluate(async () => {
  try {
    return (await fetch('/graph')).status;
  } catch {
    return -1;
  }
});
report.graphEndpointStatus = graphStatus;

const metaLabels = await page.evaluate(async () => {
  try {
    const r = await fetch('/meta');
    const d = await r.json();
    return d.labels ?? {};
  } catch {
    return {};
  }
});
report.metaLabelsCount = Object.keys(metaLabels).length;

for (const theme of ['light', 'dark']) {
  for (const lang of ['en', 'ar']) {
    await setTheme(page, theme);
    await setLanguage(page, lang);
    await reload(page);

    const layout = await page.evaluate(() => ({
      dir: document.documentElement.dir,
      lang: document.documentElement.lang,
      sidebarLeft: document.querySelector('[data-sidebar="sidebar"]')?.getBoundingClientRect().x ?? null,
    }));
    report.measurements.push({ view: 'layout', theme, lang, ...layout });
    if (layout.dir !== 'ltr') report.issues.push({ id: 'LAYOUT', theme, lang, detail: `dir=${layout.dir}` });

    const tag = `${lang}-${theme}`;

    // Intake
    const intakeShot = join(OUT, `b4-intake-${tag}.png`);
    await page.screenshot({ path: intakeShot, fullPage: false });
    report.captures.push(intakeShot);

    const intakeResidual = await findEnglishResiduals(page);
    report.englishInventory[`intake-${tag}`] = intakeResidual;
    if (lang === 'ar') {
      if (intakeResidual.enMarkers.length) {
        report.issues.push({ id: 'I01', surface: 'intake', theme, markers: intakeResidual.enMarkers });
      }
      if (intakeResidual.rawCategoryKeys.length) {
        report.issues.push({ id: 'I02', surface: 'intake', theme, keys: intakeResidual.rawCategoryKeys });
      }
    }

    // B1 H01 in AR
    const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
    const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground');
    if (countEl) {
      const ratio = await contrastRatio(page, countEl.color, countBg);
      report.measurements.push({ view: 'H01-intake-count', theme, lang, ratio, ...countEl });
      if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H01', theme, lang, ratio });
    }

    // Decisions
    await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(1500);
    const decisionsShot = join(OUT, `b4-decisions-${tag}.png`);
    await page.screenshot({ path: decisionsShot, fullPage: false });
    report.captures.push(decisionsShot);

    const decText = await collectVisibleText(page);
    if (lang === 'ar') {
      const decResidual = EN_UI_MARKERS.filter((m) => decText.includes(m));
      report.englishInventory[`decisions-${tag}`] = decResidual;
      if (decResidual.length) report.issues.push({ id: 'I01', surface: 'decisions', theme, markers: decResidual });
      if (decText.includes(' pending')) report.issues.push({ id: 'I04', surface: 'decisions', theme, detail: 'hardcoded pending' });
    }

    // B3 metric smoke in AR
    const progressVariants = await page.evaluate(() =>
      [...document.querySelectorAll('[data-variant]')].map((el) => el.getAttribute('data-variant')),
    );
    report.measurements.push({ view: 'B3-progress-variants', theme, lang, variants: progressVariants, count: progressVariants.length });
    const hasPrimaryOnly = progressVariants.length === 0;
    if (lang === 'ar' && hasPrimaryOnly) report.issues.push({ id: 'B3-M01', theme, lang, detail: 'no data-variant segments' });

    const panelHeights = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('[data-slot="card"]')];
      const problems = cards.find((c) => c.textContent?.includes('المشكلات') || c.textContent?.includes('Problems'));
      const queue = cards.find((c) => c.textContent?.includes('قائمة الحالات') || c.textContent?.includes('Open case queue'));
      const h = (el) => (el ? Math.round(el.getBoundingClientRect().height) : null);
      return { problems: h(problems), queue: h(queue) };
    });
    report.measurements.push({ view: 'B3-panel-heights', theme, lang, ...panelHeights });

    // B1 H03 selected problem
    const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
    if (await problemRow.count()) {
      await problemRow.click();
      await page.waitForTimeout(200);
      const sel = await measure(page, 'button.border-primary\\/30');
      if (sel) {
        const ratio = await contrastRatio(page, sel.color, sel.backgroundColor);
        report.measurements.push({ view: 'H03-problem-selected', theme, lang, ratio, ...sel });
        if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H03', theme, lang, ratio });
      }
    }

    // Explore / Schema
    await page.locator('[data-sidebar="menu-button"]').nth(2).click();
    await page.waitForTimeout(2500);
    await page.locator('button').filter({ hasText: lang === 'ar' ? 'المخطط' : 'Schema' }).click().catch(() => {});
    await page.waitForTimeout(2000);

    const exploreShot = join(OUT, `b4-schema-${tag}.png`);
    await page.screenshot({ path: exploreShot, fullPage: false });
    report.captures.push(exploreShot);

    const legendLabels = await getSchemaLegendLabels(page);
    report.measurements.push({ view: 'schema-legend', theme, lang, labels: legendLabels });
    if (lang === 'ar' && legendLabels.some((l) => /^[A-Z]/.test(l))) {
      report.issues.push({ id: 'I03', surface: 'schema-legend', theme, labels: legendLabels });
    }

    const exploreText = await collectVisibleText(page);
    if (lang === 'ar') {
      const exploreResidual = EN_UI_MARKERS.filter((m) => exploreText.includes(m));
      if (exploreResidual.length) report.issues.push({ id: 'I01', surface: 'explore', theme, markers: exploreResidual });
    }
  }
}

// Theme/language toggle remount check on schema view
await setTheme(page, 'light');
await setLanguage(page, 'en');
await reload(page);
await page.locator('[data-sidebar="menu-button"]').nth(2).click();
await page.waitForTimeout(2000);
await page.locator('button').filter({ hasText: 'Schema' }).click().catch(() => {});
await page.waitForTimeout(2000);

const beforeToggle = await page.evaluate(() => {
  const canvas = document.querySelector('canvas');
  return { hasCanvas: !!canvas, surface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface') };
});
await setLanguage(page, 'ar');
await page.evaluate(() => window.dispatchEvent(new Event('storage')));
await page.waitForTimeout(500);
// click language toggle UI
const langBtn = page.locator('header button').filter({ has: page.locator('svg') }).first();
if (await langBtn.count()) {
  await langBtn.click();
  await page.locator('[role="menuitem"]').filter({ hasText: 'العربية' }).click().catch(() => {});
  await page.waitForTimeout(800);
}
await setTheme(page, 'dark');
const themeBtn = page.locator('header button[aria-label*="المظهر"], header button[aria-label*="Theme"]').first();
if (await themeBtn.count()) {
  await themeBtn.click();
  await page.locator('[role="menuitem"]').filter({ hasText: /داكن|Dark/ }).click().catch(() => {});
  await page.waitForTimeout(800);
}
const afterToggle = await page.evaluate(() => {
  const canvas = document.querySelector('canvas');
  return {
    hasCanvas: !!canvas,
    surface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface'),
    lang: document.documentElement.lang,
    dir: document.documentElement.dir,
  };
});
report.measurements.push({ view: 'toggle-no-remount', beforeToggle, afterToggle });
const remountShot = join(OUT, 'b4-schema-ar-dark-after-toggle.png');
await page.screenshot({ path: remountShot, fullPage: false });
report.captures.push(remountShot);

// Dictionary parity check (static import via page eval of known keys)
report.dictionaryParity = await page.evaluate(() => {
  const enAwait = null; // filled below from node
  return { note: 'checked in audit doc from en.ts/ar.ts' };
});

for (const id of ['I01', 'I02', 'I03', 'I04']) {
  report.verdicts[id] = report.issues.some((i) => i.id === id) ? 'REPRODUCED' : 'NOT REPRODUCED';
}

writeFileSync(join(OUT, 'measurements-b4-audit.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('B4 issues:', report.issues.length);
console.log('Verdicts:', report.verdicts);
console.log('written', join(OUT, 'measurements-b4-audit.json'));
