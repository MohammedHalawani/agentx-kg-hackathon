import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.evaluate(() => {
  localStorage.setItem('agentx-language', 'ar');
  localStorage.setItem('agentx-theme', 'light');
});
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(1000);
await page.locator('[data-sidebar="menu-button"]').nth(1).click();
await page.waitForTimeout(1200);
const tones = await page.evaluate(() => {
  const cards = [...document.querySelectorAll('.grid.gap-3.sm\\:grid-cols-2.xl\\:grid-cols-5 > div')];
  return cards.map((c) => {
    const label = c.querySelector('p.text-xs')?.textContent;
    const icon = c.querySelector('.grid.size-8');
    return {
      label,
      iconClass: icon?.className || null,
      warning: icon?.className.includes('text-chart-warning'),
      good: icon?.className.includes('text-chart-good'),
    };
  });
});
console.log(JSON.stringify(tones, null, 2));
await browser.close();
