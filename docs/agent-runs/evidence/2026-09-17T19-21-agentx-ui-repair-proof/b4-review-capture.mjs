/**
 * Agent C (B4 Review) — independent verification @ 1440×900
 * Candidate build: index-DVhlRZ8U.css / index-DE557tU5.js
 */
import { chromium } from 'playwright'
import { writeFileSync } from 'fs'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const OUT = __dirname
const BASE = 'http://127.0.0.1:8000'
const CANDIDATE_CSS = 'index-DVhlRZ8U.css'
const CANDIDATE_JS = 'index-DE557tU5.js'

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
  ' pending',
  'shipment(s) awaiting',
  'Category',
  'Verdict',
  'Confidence',
  'Toggle Sidebar',
  'Application',
]

const RAW_CATEGORY_PATTERNS = [
  /^recipient unavailable$/i,
  /^hub delay$/i,
  /^address conflict$/i,
  /^escalation:/i,
  /^[a-z]+(_[a-z]+)+$/,
]

async function setTheme(page, theme) {
  await page.evaluate((t) => {
    localStorage.setItem('agentx-theme', t)
    const dark = t === 'dark'
    document.documentElement.classList.toggle('dark', dark)
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light'
  }, theme)
}

async function setLanguage(page, lang) {
  await page.evaluate((l) => {
    localStorage.setItem('agentx-language', l)
    document.documentElement.lang = l
    document.documentElement.dir = 'ltr'
  }, lang)
}

async function reload(page) {
  await page.reload({ waitUntil: 'networkidle' })
  await page.waitForTimeout(1200)
}

async function measure(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    const cs = getComputedStyle(el)
    const rect = el.getBoundingClientRect()
    return {
      selector: sel,
      color: cs.color,
      backgroundColor: cs.backgroundColor,
      text: (el.textContent || '').slice(0, 80),
      rect: { x: rect.x, y: rect.y, w: rect.width, h: rect.height },
    }
  }, selector)
}

async function effectiveBg(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel)
    if (!el) return null
    let node = el
    while (node) {
      const bg = getComputedStyle(node).backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)') return bg
      node = node.parentElement
    }
    return getComputedStyle(document.body).backgroundColor
  }, selector)
}

async function contrastRatio(page, fg, bg) {
  return page.evaluate(({ fg, bg }) => {
    const parse = (c) => {
      const m = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
      if (!m) return null
      return [+m[1], +m[2], +m[3]].map((v) => v / 255)
    }
    const lum = (rgb) => {
      const f = rgb.map((x) => (x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)))
      return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2]
    }
    const a = parse(fg)
    const b = parse(bg)
    if (!a || !b) return null
    const L1 = lum(a)
    const L2 = lum(b)
    const hi = Math.max(L1, L2)
    const lo = Math.min(L1, L2)
    return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100
  }, { fg, bg })
}

async function findEnglishResiduals(page) {
  return page.evaluate(
    ({ markers, rawPatterns }) => {
      const body = document.body.innerText || ''
      const hits = markers.filter((m) => body.includes(m))
      const metaSpans = [...document.querySelectorAll('button span')].map((s) => s.textContent?.trim()).filter(Boolean)
      const rawCats = metaSpans.filter((t) => rawPatterns.some((p) => new RegExp(p).test(t)))
      const scopeText = document.querySelector('header span.hidden')?.textContent?.trim() ?? ''
      const scopeEnglish = scopeText.includes('Autonomous shipment')
      return { enMarkers: hits, rawCategoryKeys: rawCats.slice(0, 10), scopeEnglish, scopeText }
    },
    { markers: EN_UI_MARKERS, rawPatterns: RAW_CATEGORY_PATTERNS.map((r) => r.source) },
  )
}

async function getSchemaLegendLabels(page) {
  return page.evaluate(() => {
    const legend = document.querySelector('.pointer-events-none.absolute.left-3.top-3')
    if (!legend) return []
    return [...legend.querySelectorAll('span.pointer-events-auto')]
      .map((s) => s.childNodes[0]?.textContent?.trim())
      .filter(Boolean)
  })
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const report = {
  url: BASE,
  viewport: '1440x900',
  phase: 'b4-review',
  agent: 'C',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  captures: [],
  measurements: [],
  issues: [],
  englishInventory: {},
  verdicts: {},
}

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}))

const jsServed = report.buildFingerprint.js.some((s) => s.includes(CANDIDATE_JS))
if (!jsServed) {
  report.issues.push({ id: 'BUILD', detail: `Expected ${CANDIDATE_JS} not served` })
}

for (const theme of ['light', 'dark']) {
  for (const lang of ['ar']) {
    await setTheme(page, theme)
    await setLanguage(page, lang)
    await reload(page)

    const layout = await page.evaluate(() => ({
      dir: document.documentElement.dir,
      lang: document.documentElement.lang,
      sidebarLeft: document.querySelector('[data-sidebar="sidebar"]')?.getBoundingClientRect().x ?? null,
    }))
    report.measurements.push({ view: 'layout', theme, lang, ...layout })
    if (layout.dir !== 'ltr') report.issues.push({ id: 'SAFETY', theme, lang, detail: `dir=${layout.dir}` })

    const tag = `${lang}-${theme}`

    // Intake
    const intakeShot = join(OUT, `b4-review-intake-${tag}.png`)
    await page.screenshot({ path: intakeShot, fullPage: false })
    report.captures.push(intakeShot)

    const intakeResidual = await findEnglishResiduals(page)
    report.englishInventory[`intake-${tag}`] = intakeResidual
    if (intakeResidual.enMarkers.length) {
      report.issues.push({ id: 'I01', surface: 'intake', theme, markers: intakeResidual.enMarkers })
    }
    if (intakeResidual.rawCategoryKeys.length) {
      report.issues.push({ id: 'I02', surface: 'intake', theme, keys: intakeResidual.rawCategoryKeys })
    }
    if (intakeResidual.scopeEnglish) {
      report.issues.push({ id: 'I01', surface: 'scope', theme, detail: intakeResidual.scopeText })
    }

    // B1 H01
    const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground')
    const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground')
    if (countEl) {
      const ratio = await contrastRatio(page, countEl.color, countBg)
      report.measurements.push({ view: 'H01-intake-count', theme, lang, ratio, ...countEl })
      if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H01', theme, lang, ratio })
    }

    // Decisions
    await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(1500)
    const decisionsShot = join(OUT, `b4-review-decisions-${tag}.png`)
    await page.screenshot({ path: decisionsShot, fullPage: false })
    report.captures.push(decisionsShot)

    const decText = await page.evaluate(() => document.body.innerText || '')
    const decResidual = EN_UI_MARKERS.filter((m) => decText.includes(m))
    report.englishInventory[`decisions-${tag}`] = decResidual
    if (decResidual.length) report.issues.push({ id: 'I01', surface: 'decisions', theme, markers: decResidual })
    if (decText.includes(' pending')) report.issues.push({ id: 'I04', surface: 'decisions', theme, detail: 'hardcoded pending' })

    // B3 metric smoke
    const progressVariants = await page.evaluate(() =>
      [...document.querySelectorAll('[data-variant]')].map((el) => el.getAttribute('data-variant')),
    )
    report.measurements.push({ view: 'B3-progress-variants', theme, lang, count: progressVariants.length, variants: progressVariants.slice(0, 35) })
    if (progressVariants.length < 20) report.issues.push({ id: 'B3-M01', theme, lang, detail: 'few data-variant segments' })

    const panelHeights = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('[data-slot="card"]')]
      const problems = cards.find((c) => c.textContent?.includes('المشكلات'))
      const queue = cards.find((c) => c.textContent?.includes('قائمة الحالات'))
      const h = (el) => (el ? Math.round(el.getBoundingClientRect().height) : null)
      return { problems: h(problems), queue: h(queue) }
    })
    report.measurements.push({ view: 'B3-panel-heights', theme, lang, ...panelHeights })

    // B1 H03
    const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first()
    if (await problemRow.count()) {
      await problemRow.click()
      await page.waitForTimeout(200)
      const sel = await measure(page, 'button.border-primary\\/30')
      if (sel) {
        const ratio = await contrastRatio(page, sel.color, sel.backgroundColor)
        report.measurements.push({ view: 'H03-problem-selected', theme, lang, ratio, ...sel })
        if (ratio !== null && ratio < 4.5) report.issues.push({ id: 'H03', theme, lang, ratio })
      }
    }

    // Schema
    await page.locator('[data-sidebar="menu-button"]').nth(2).click()
    await page.waitForTimeout(2500)
    await page.locator('button').filter({ hasText: 'المخطط' }).click().catch(() => {})
    await page.waitForTimeout(2000)

    const schemaShot = join(OUT, `b4-review-schema-${tag}.png`)
    await page.screenshot({ path: schemaShot, fullPage: false })
    report.captures.push(schemaShot)

    const legendLabels = await getSchemaLegendLabels(page)
    report.measurements.push({ view: 'schema-legend', theme, lang, labels: legendLabels })
    const englishLegend = legendLabels.filter((l) => /^[A-Z]/.test(l))
    if (englishLegend.length) {
      report.issues.push({ id: 'I03', surface: 'schema-legend', theme, labels: englishLegend })
    }
  }
}

// Toggle persistence check
await setTheme(page, 'light')
await setLanguage(page, 'en')
await reload(page)
await page.locator('[data-sidebar="menu-button"]').nth(2).click()
await page.waitForTimeout(2000)
await page.locator('button').filter({ hasText: 'Schema' }).click().catch(() => {})
await page.waitForTimeout(2000)
const beforeToggle = await page.evaluate(() => ({
  hasCanvas: !!document.querySelector('canvas'),
  surface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface'),
}))
await setLanguage(page, 'ar')
await page.evaluate(() => window.dispatchEvent(new Event('storage')))
await page.waitForTimeout(500)
const langBtn = page.locator('header button').filter({ has: page.locator('svg') }).first()
if (await langBtn.count()) {
  await langBtn.click()
  await page.locator('[role="menuitem"]').filter({ hasText: 'العربية' }).click().catch(() => {})
  await page.waitForTimeout(800)
}
await setTheme(page, 'dark')
const themeBtn = page.locator('header button[aria-label*="المظهر"], header button[aria-label*="Theme"]').first()
if (await themeBtn.count()) {
  await themeBtn.click()
  await page.locator('[role="menuitem"]').filter({ hasText: /داكن|Dark/ }).click().catch(() => {})
  await page.waitForTimeout(800)
}
const afterToggle = await page.evaluate(() => ({
  hasCanvas: !!document.querySelector('canvas'),
  surface: getComputedStyle(document.documentElement).getPropertyValue('--color-surface'),
  lang: document.documentElement.lang,
  dir: document.documentElement.dir,
}))
report.measurements.push({ view: 'toggle-no-remount', beforeToggle, afterToggle })
if (!afterToggle.hasCanvas) report.issues.push({ id: 'SAFETY', detail: 'canvas lost after lang/theme toggle' })

for (const id of ['I01', 'I02', 'I03', 'I04']) {
  report.verdicts[id] = report.issues.some((i) => i.id === id) ? 'FAIL' : 'PASS'
}

writeFileSync(join(OUT, 'measurements-b4-review.json'), JSON.stringify(report, null, 2))
await browser.close()
console.log('B4 review issues:', report.issues.length)
console.log('Verdicts:', report.verdicts)
console.log('written', join(OUT, 'measurements-b4-review.json'))
