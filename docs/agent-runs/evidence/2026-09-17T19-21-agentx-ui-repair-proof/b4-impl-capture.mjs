/**
 * B4 Implementation — AR after screenshots @ 1440×900
 */
import { chromium } from 'playwright'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = __dirname
const BASE = 'http://127.0.0.1:8000'

async function setLanguage(page, lang) {
  await page.evaluate((l) => {
    localStorage.setItem('agentx-language', l)
    document.documentElement.lang = l
    document.documentElement.dir = 'ltr'
  }, lang)
}

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t)
    const dark = t === 'dark'
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  }, theme)
}

async function goView(page, view) {
  await page.evaluate((v) => {
    window.dispatchEvent(new CustomEvent('agentx-nav', { detail: v }))
  }, view)
}

async function capture(page, name) {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(BASE, { waitUntil: 'networkidle' })
  await setLanguage(page, 'ar')
  await setTheme(page, 'light')
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1500)
  await page.screenshot({ path: join(OUT, name), fullPage: false })
}

const browser = await chromium.launch()
const page = await browser.newPage()

// Intake
await capture(page, 'b4-intake-ar-light-after.png')

// Decisions — click nav
await page.getByRole('button', { name: 'القرارات' }).click()
await page.waitForTimeout(1200)
await page.screenshot({ path: join(OUT, 'b4-decisions-ar-light-after.png'), fullPage: false })

// Schema — Explore then Schema lens
await page.getByRole('button', { name: 'الاستكشاف' }).click()
await page.waitForTimeout(800)
await page.getByRole('button', { name: 'المخطط' }).click()
await page.waitForTimeout(2000)
await page.screenshot({ path: join(OUT, 'b4-schema-ar-light-after.png'), fullPage: false })

await browser.close()
console.log('Captured b4-*-after.png to', OUT)
