import { chromium } from 'playwright';
import { writeFileSync, mkdirSync } from 'fs';
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
const report = { url: BASE, viewport: '1440x900', captures: [], measurements: [] };

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.waitForTimeout(1500);

const assets = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
  theme: localStorage.getItem('agentx-theme'),
  dark: document.documentElement.classList.contains('dark'),
}));

report.buildFingerprint = assets;

for (const theme of ['light', 'dark']) {
  await setTheme(page, theme);
  await page.reload({ waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);

  // Intake default
  const intakeShot = join(OUT, `intake-${theme}-default.png`);
  await page.screenshot({ path: intakeShot, fullPage: false });
  report.captures.push(intakeShot);

  const countEl = await measure(page, 'h2 + span.text-muted, h2 ~ span.text-sm.text-muted');
  const descEl = await measure(page, 'p.text-muted');
  const metaEl = await measure(page, 'button span.text-muted');
  report.measurements.push({ theme, view: 'intake', countEl, descEl, metaEl });

  if (countEl) {
    report.measurements.push({
      theme,
      view: 'intake-count-contrast',
      ratio: await contrastRatio(page, countEl.color, countEl.backgroundColor),
      ...countEl,
    });
  }

  // Intake hover first case button
  const caseBtn = page.locator('button').filter({ hasText: /SHP-/ }).first();
  if (await caseBtn.count()) {
    await caseBtn.hover();
    await page.waitForTimeout(300);
    const hoverShot = join(OUT, `intake-${theme}-hover.png`);
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

  // Decisions view
  await page.locator('button, a').filter({ hasText: /Decisions|القرارات/i }).first().click({ timeout: 5000 }).catch(() =>
    page.evaluate(() => {
      const items = [...document.querySelectorAll('[data-sidebar="menu-button"]')];
      items[1]?.click();
    }),
  );
  await page.waitForTimeout(1500);
  const decShot = join(OUT, `decisions-${theme}-default.png`);
  await page.screenshot({ path: decShot, fullPage: false });
  report.captures.push(decShot);

  // Problems row selected + hover
  const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first();
  if (await problemRow.count()) {
    await problemRow.click();
    await page.waitForTimeout(200);
    const selShot = join(OUT, `decisions-${theme}-problem-selected.png`);
    await page.screenshot({ path: selShot, fullPage: false });
    report.captures.push(selShot);
    const sel = await measure(page, 'button.border-primary\\/30');
    report.measurements.push({ theme, view: 'problem-selected', sel });

    const unselected = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).nth(1);
    if (await unselected.count()) {
      await unselected.hover();
      await page.waitForTimeout(200);
      const hoverProb = join(OUT, `decisions-${theme}-problem-hover.png`);
      await page.screenshot({ path: hoverProb, fullPage: false });
      report.captures.push(hoverProb);
    }
  }

  // Queue row hover/selected
  const queueRow = page.locator('tr[data-state="selected"], tbody tr').first();
  if (await queueRow.count()) {
    await queueRow.hover();
    await page.waitForTimeout(200);
    const qHover = join(OUT, `decisions-${theme}-queue-hover.png`);
    await page.screenshot({ path: qHover, fullPage: false });
    report.captures.push(qHover);
    const qCell = await measure(page, 'tbody tr:first-child td');
    report.measurements.push({ theme, view: 'queue-row', qCell });
  }

  // Sidebar hover vs active
  const navItems = page.locator('[data-sidebar="menu-button"]');
  const activeIdx = theme === 'light' ? 1 : 1;
  if (await navItems.count() >= 2) {
    await navItems.nth(0).hover();
    await page.waitForTimeout(200);
    const sideHover = join(OUT, `sidebar-${theme}-hover-intake.png`);
    await page.screenshot({ path: sideHover, fullPage: false });
    report.captures.push(sideHover);
  }

  // Explore graph controls
  await page.locator('[data-sidebar="menu-button"]').nth(2).click();
  await page.waitForTimeout(2500);
  const exploreShot = join(OUT, `explore-${theme}-graph.png`);
  await page.screenshot({ path: exploreShot, fullPage: false });
  report.captures.push(exploreShot);

  const lensSelected = await measure(page, 'button .absolute.inset-0.rounded-md.bg-primary');
  report.measurements.push({ theme, view: 'explore-lens', lensSelected });

  const layoutSelected = await measure(page, '.absolute.right-3.top-3 button.bg-primary, .absolute.bottom-3 button.bg-primary');
  report.measurements.push({ theme, view: 'graph-controls', layoutSelected });
}

writeFileSync(join(OUT, 'measurements.json'), JSON.stringify(report, null, 2));
await browser.close();
console.log('done', join(OUT, 'measurements.json'));
