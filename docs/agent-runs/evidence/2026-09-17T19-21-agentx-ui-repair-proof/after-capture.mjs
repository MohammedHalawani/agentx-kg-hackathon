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
      text: (el.textContent || '').slice(0, 80),
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
const report = { url: BASE, viewport: '1440x900', phase: 'after', captures: [], measurements: [] };

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
  theme: localStorage.getItem('agentx-theme'),
  dark: document.documentElement.classList.contains('dark'),
}));

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  const intakeShot = join(OUT, `intake-${theme}-default-after.png`);
  await page.screenshot({ path: intakeShot, fullPage: false });
  report.captures.push(intakeShot);

  const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground');
  const descEl = await measure(page, 'p.text-muted-foreground');
  const metaEl = await measure(page, 'button span.text-muted-foreground');
  report.measurements.push({ theme, view: 'intake', countEl, descEl, metaEl });

  if (countEl) {
    report.measurements.push({
      theme,
      view: 'intake-count-contrast',
      ratio: await contrastRatio(page, countEl.color, 'rgb(250, 249, 247)'),
      ...countEl,
    });
  }

  const caseBtn = page.locator('button').filter({ hasText: /SHP-/ }).first();
  if (await caseBtn.count()) {
    await caseBtn.hover();
    await page.waitForTimeout(300);
    const hoverShot = join(OUT, `intake-${theme}-hover-after.png`);
    await page.screenshot({ path: hoverShot, fullPage: false });
    report.captures.push(hoverShot);
    const hoverBtn = await measure(page, 'button:hover');
    report.measurements.push({ theme, view: 'intake-hover', hoverBtn });
    if (hoverBtn) {
      report.measurements.push({
        theme,
        view: 'intake-hover-contrast',
        ratio: await contrastRatio(page, hoverBtn.color, hoverBtn.backgroundColor),
        ...hoverBtn,
      });
    }
  }

  await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(1500);
  const decShot = join(OUT, `decisions-${theme}-default-after.png`);
  await page.screenshot({ path: decShot, fullPage: false });
  report.captures.push(decShot);

  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const selShot = join(OUT, `decisions-${theme}-problem-selected-after.png`);
    await page.screenshot({ path: selShot, fullPage: false });
    report.captures.push(selShot);
    const sel = await measure(page, 'button.border-primary\\/30');
    report.measurements.push({ theme, view: 'problem-selected', sel });
    if (sel) {
      report.measurements.push({
        theme,
        view: 'problem-selected-contrast',
        ratio: await contrastRatio(page, sel.color, sel.backgroundColor),
        ...sel,
      });
    }
  }

  const queueRow = page.locator('tbody tr').first();
  if (await queueRow.count()) {
    await queueRow.click();
    await queueRow.hover();
    await page.waitForTimeout(200);
    const qHover = join(OUT, `decisions-${theme}-queue-hover-after.png`);
    await page.screenshot({ path: qHover, fullPage: false });
    report.captures.push(qHover);
    const qCell = await measure(page, 'tbody tr:first-child td');
    report.measurements.push({ theme, view: 'queue-row', qCell });
  }

  await page.locator('[data-sidebar="menu-button"]').nth(0).hover();
  await page.waitForTimeout(200);
  const sideHover = join(OUT, `sidebar-${theme}-hover-intake-after.png`);
  await page.screenshot({ path: sideHover, fullPage: false });
  report.captures.push(sideHover);

  await page.locator('[data-sidebar="menu-button"]').nth(2).click();
  await page.waitForTimeout(2500);
  const exploreShot = join(OUT, `explore-${theme}-graph-after.png`);
  await page.screenshot({ path: exploreShot, fullPage: false });
  report.captures.push(exploreShot);

  const lensSelected = await measure(page, 'button .absolute.inset-0.rounded-md.bg-primary');
  report.measurements.push({ theme, view: 'explore-lens', lensSelected });
  if (lensSelected) {
    report.measurements.push({
      theme,
      view: 'explore-lens-contrast',
      ratio: await contrastRatio(page, lensSelected.color, lensSelected.backgroundColor),
      ...lensSelected,
    });
  }
}

writeFileSync(join(OUT, 'measurements-after.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('done', join(OUT, 'measurements-after.json'));
