import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1500);

const stickyTest = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const vp = card?.querySelector('[data-slot="scroll-area-viewport"]');
  const thead = card?.querySelector('thead.sticky');
  if (!vp || !thead) return { ok: false };

  vp.scrollTop = 500;
  const vpRect = vp.getBoundingClientRect();
  const theadRect = thead.getBoundingClientRect();
  const firstRow = vp.querySelector('tbody tr');
  const firstRowRect = firstRow?.getBoundingClientRect();

  return {
    ok: true,
    scrollTop: vp.scrollTop,
    theadTop: theadRect.top,
    viewportTop: vpRect.top,
    headerPinnedToViewportTop: Math.abs(theadRect.top - vpRect.top) < 3,
    firstRowBelowHeader: firstRowRect ? firstRowRect.top >= theadRect.bottom - 2 : null,
    headerStillVisible: theadRect.bottom > vpRect.top && theadRect.top < vpRect.bottom,
  };
});

// Focus panel: select category with many open cases, test inner table scroll
const focusOverflow = await page.evaluate(async () => {
  const buttons = [...document.querySelectorAll('button')].filter((b) => b.querySelector('.line-clamp-2'));
  // click first category
  buttons[0]?.click();
  await new Promise((r) => setTimeout(r, 300));
  const focusCard = [...document.querySelectorAll('.h-\\[440px\\]')].find((c) =>
    c.textContent?.includes('Focus'),
  );
  const vp = focusCard?.querySelector('[data-slot="scroll-area-viewport"]');
  const innerTable = focusCard?.querySelector('table');
  const innerThead = innerTable?.querySelector('thead');
  return {
    focusScroll: vp
      ? { sh: vp.scrollHeight, ch: vp.clientHeight, overflows: vp.scrollHeight > vp.clientHeight }
      : null,
    innerTableHasSticky: innerThead ? getComputedStyle(innerThead).position : 'no-inner-table',
    matchingRows: innerTable?.querySelectorAll('tbody tr').length ?? 0,
  };
});

console.log(JSON.stringify({ stickyTest, focusOverflow }, null, 2));
await browser.close();
