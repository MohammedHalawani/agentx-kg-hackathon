import { chromium } from 'playwright';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1500);

const result = await page.evaluate(() => {
  const queueCard = document.querySelector('.h-\\[400px\\]');
  const vp = queueCard?.querySelector('[data-slot="scroll-area-viewport"]');
  const thead = queueCard?.querySelector('thead.sticky');
  return {
    queueOuterH: queueCard ? Math.round(queueCard.getBoundingClientRect().height) : null,
    queueScroll: vp
      ? {
          scrollHeight: vp.scrollHeight,
          clientHeight: vp.clientHeight,
          overflows: vp.scrollHeight > vp.clientHeight + 2,
        }
      : null,
    stickyHeader: thead
      ? {
          position: getComputedStyle(thead).position,
          top: getComputedStyle(thead).top,
          zIndex: getComputedStyle(thead).zIndex,
        }
      : null,
    allHeights: [...document.querySelectorAll('[data-slot="card"]')].map((c) => ({
      h: Math.round(c.getBoundingClientRect().height),
      has400: c.className.includes('h-[400px]'),
      has440: c.className.includes('h-[440px]'),
      title: c.querySelector('[data-slot="card-title"]')?.textContent?.slice(0, 50),
    })),
  };
});

// scroll queue to end
const reach = await page.evaluate(() => {
  const card = document.querySelector('.h-\\[400px\\]');
  const vp = card?.querySelector('[data-slot="scroll-area-viewport"]');
  if (!vp) return { scrolled: false };
  vp.scrollTop = vp.scrollHeight;
  const rows = vp.querySelectorAll('tbody tr');
  const last = rows[rows.length - 1];
  const vpRect = vp.getBoundingClientRect();
  const lastRect = last?.getBoundingClientRect();
  return {
    scrolled: true,
    scrollTop: vp.scrollTop,
    scrollHeight: vp.scrollHeight,
    clientHeight: vp.clientHeight,
    atEnd: vp.scrollTop + vp.clientHeight >= vp.scrollHeight - 4,
    lastRowVisible: lastRect ? lastRect.top >= vpRect.top && lastRect.bottom <= vpRect.bottom + 2 : false,
    rowCount: rows.length,
  };
});

console.log(JSON.stringify({ ...result, reach }, null, 2));
await browser.close();
