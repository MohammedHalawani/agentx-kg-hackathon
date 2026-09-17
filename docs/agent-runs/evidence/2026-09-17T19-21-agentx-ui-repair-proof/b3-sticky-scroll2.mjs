import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1500);

// Scroll page so queue card is in view
await page.locator('.h-\\[400px\\]').scrollIntoViewIfNeeded();
await page.waitForTimeout(300);

const stickyTest = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const vp = card?.querySelector('[data-slot="scroll-area-viewport"]');
  const thead = card?.querySelector('thead.sticky');
  if (!vp || !thead) return { ok: false };

  const before = {
    vpTop: vp.getBoundingClientRect().top,
    theadTop: thead.getBoundingClientRect().top,
  };

  vp.scrollTop = 400;
  const after = {
    scrollTop: vp.scrollTop,
    vpTop: vp.getBoundingClientRect().top,
    theadTop: thead.getBoundingClientRect().top,
    theadPosition: getComputedStyle(thead).position,
  };

  return {
    ok: true,
    before,
    after,
    headerPinned: Math.abs(after.theadTop - after.vpTop) < 4,
    headerScrolledAway: after.theadTop < after.vpTop - 2,
  };
});

console.log(JSON.stringify(stickyTest, null, 2));
await browser.close();
