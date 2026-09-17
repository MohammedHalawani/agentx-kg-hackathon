/**
 * Closure Reviewer 5A — independent B1 revalidation @ 1440×900
 * Frozen candidate: index-DVhlRZ8U.css / index-DE557tU5.js
 * Matrix: EN+AR × Light+Dark; pointer hover ACTIVE for interaction states
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
const RUN_ID = '2026-09-17T19-21-agentx-ui-repair-proof'
const SURFACES = { light: 'rgb(250, 249, 247)', dark: 'rgb(17, 19, 24)' }

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
      className: el.className,
      text: (el.textContent || '').slice(0, 80),
      fontSize: cs.fontSize,
      fontWeight: cs.fontWeight,
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

async function captureMenu(page, kind, lang, theme) {
  const label =
    kind === 'theme'
      ? lang === 'ar'
        ? 'المظهر'
        : 'Theme'
      : lang === 'ar'
        ? 'اللغة'
        : 'Language'
  const btn = page
    .locator(
      `header button[aria-label*="${label}"], header button[aria-label*="${kind === 'theme' ? 'Theme' : 'Language'}"]`,
    )
    .first()
  if (!(await btn.count())) return null
  await btn.click()
  await page.waitForTimeout(400)
  const shot = join(OUT, `b1-closure-${kind}-menu-${lang}-${theme}.png`)
  await page.screenshot({ path: shot, fullPage: false })
  const items = await page.evaluate(() =>
    [...document.querySelectorAll('[role="menuitem"]')].map((el) => el.textContent?.trim()).filter(Boolean),
  )
  const firstItem = page.locator('[role="menuitem"]').first()
  if (await firstItem.count()) {
    await firstItem.hover()
    await page.waitForTimeout(200)
    const hoverItem = await measure(page, '[role="menuitem"]:hover')
    await page.keyboard.press('Escape')
    await page.waitForTimeout(200)
    return { shot, items, hoverItem }
  }
  await page.keyboard.press('Escape')
  await page.waitForTimeout(200)
  return { shot, items, hoverItem: null }
}

function pushIssue(report, issue) {
  report.issues.push(issue)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
const report = {
  runId: RUN_ID,
  phase: 'b1-closure',
  agent: '5A',
  url: BASE,
  viewport: '1440x900',
  candidateBuild: { css: CANDIDATE_CSS, js: CANDIDATE_JS },
  baselineRef: 'measurements-gate.json (B1 gate @ index-B9I8LKnG.css)',
  captures: [],
  measurements: [],
  menuCaptures: [],
  issues: [],
  verdicts: {},
}

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

report.buildFingerprint = await page.evaluate(() => ({
  css: [...document.querySelectorAll('link[rel=stylesheet]')].map((l) => l.href),
  js: [...document.querySelectorAll('script[src]')].map((s) => s.src),
}))

const cssServed = report.buildFingerprint.css.some((s) => s.includes(CANDIDATE_CSS))
const jsServed = report.buildFingerprint.js.some((s) => s.includes(CANDIDATE_JS))
if (!cssServed || !jsServed) {
  pushIssue(report, {
    id: 'BUILD',
    severity: 'BLOCKER',
    detail: `Expected ${CANDIDATE_CSS}/${CANDIDATE_JS}; css=${cssServed} js=${jsServed}`,
  })
}

report.endpoint = await page.evaluate(async () => {
  const probe = async (path) => {
    try {
      const r = await fetch(path)
      return { status: r.status, ok: r.ok }
    } catch {
      return { status: -1, ok: false }
    }
  }
  return { graph: await probe('/graph'), schema: await probe('/schema') }
})

for (const theme of ['light', 'dark']) {
  for (const lang of ['en', 'ar']) {
    await setTheme(page, theme)
    await setLanguage(page, lang)
    await reload(page)
    const tag = `${lang}-${theme}`

    const themeMenu = await captureMenu(page, 'theme', lang, theme)
    if (themeMenu) {
      report.captures.push(themeMenu.shot)
      report.menuCaptures.push({ kind: 'theme', lang, theme, items: themeMenu.items, hover: themeMenu.hoverItem })
    }
    const langMenu = await captureMenu(page, 'language', lang, theme)
    if (langMenu) {
      report.captures.push(langMenu.shot)
      report.menuCaptures.push({ kind: 'language', lang, theme, items: langMenu.items, hover: langMenu.hoverItem })
    }

    // H01
    const countEl = await measure(page, 'h2 ~ span.text-sm.text-muted-foreground')
    const countBg = await effectiveBg(page, 'h2 ~ span.text-sm.text-muted-foreground')
    if (countEl) {
      const ratio = await contrastRatio(page, countEl.color, countBg || SURFACES[theme])
      report.measurements.push({ view: 'H01-intake-count', theme, lang, ratio, color: countEl.color, bg: countBg, ...countEl })
      if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H01', theme, lang, ratio })
    } else {
      pushIssue(report, { id: 'H01', theme, lang, detail: 'count selector missing' })
    }

    // H02 pointer hover
    const caseBtn = page.locator('button').filter({ hasText: /SHP-/ }).first()
    if (await caseBtn.count()) {
      await caseBtn.hover()
      await page.waitForTimeout(300)
      const hoverBtn = await measure(page, 'button:hover')
      const h02Shot = join(OUT, `b1-closure-intake-hover-${tag}.png`)
      await page.screenshot({ path: h02Shot, fullPage: false })
      report.captures.push(h02Shot)
      if (hoverBtn) {
        const ratio = await contrastRatio(page, hoverBtn.color, hoverBtn.backgroundColor)
        report.measurements.push({ view: 'H02-intake-hover', theme, lang, ratio, pointerHover: true, ...hoverBtn })
        if (hoverBtn.backgroundColor.includes('232, 241, 252') && theme === 'dark') {
          pushIssue(report, { id: 'H02', theme, lang, detail: 'dark hover #e8f1fc regression' })
        }
        if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H02', theme, lang, ratio })
      }
    } else {
      pushIssue(report, { id: 'H02', theme, lang, detail: 'no case button for hover' })
    }

    // Decisions
    await page.locator('[data-sidebar="menu-button"]').nth(1).click({ timeout: 5000 }).catch(() => {})
    await page.waitForTimeout(1500)

    // H03
    const problemRow = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).first()
    if (await problemRow.count()) {
      await problemRow.click()
      await page.waitForTimeout(200)
      const sel = await measure(page, 'button.border-primary\\/30')
      if (sel) {
        const ratio = await contrastRatio(page, sel.color, sel.backgroundColor)
        report.measurements.push({ view: 'H03-problem-selected', theme, lang, ratio, ...sel })
        if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H03', theme, lang, ratio, state: 'selected' })
      }
      await problemRow.hover()
      await page.waitForTimeout(200)
      const selHover = await measure(page, 'button.border-primary\\/30:hover')
      if (selHover) {
        const ratio = await contrastRatio(page, selHover.color, selHover.backgroundColor)
        report.measurements.push({ view: 'H03-problem-selected-hover', theme, lang, ratio, pointerHover: true, ...selHover })
        if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H03', theme, lang, ratio, state: 'selected+hover' })
      }
      const problemRow2 = page.locator('button').filter({ has: page.locator('.line-clamp-2') }).nth(1)
      if (await problemRow2.count()) {
        await problemRow2.hover()
        await page.waitForTimeout(200)
        const hoverProb = await measure(page, 'button:hover')
        if (hoverProb) {
          const ratio = await contrastRatio(page, hoverProb.color, hoverProb.backgroundColor)
          report.measurements.push({ view: 'H03-problem-hover', theme, lang, ratio, pointerHover: true, ...hoverProb })
          if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H03', theme, lang, ratio, state: 'hover' })
        }
      }
    }

    // H04 queue selected+hover
    let queueRow = page.locator('tr[data-state="selected"]').first()
    if (!(await queueRow.count())) {
      const mainQueueRow = page.locator('table').filter({ has: page.locator('th') }).last().locator('tbody tr').first()
      if (await mainQueueRow.count()) await mainQueueRow.click()
    }
    queueRow = page.locator('tr[data-state="selected"]').first()
    if (await queueRow.count()) {
      await queueRow.hover()
      await page.waitForTimeout(200)
      const qCell = await measure(page, 'tr[data-state="selected"] td:nth-child(2)')
      const rowBg = await effectiveBg(page, 'tr[data-state="selected"]')
      if (qCell) {
        const ratio = await contrastRatio(page, qCell.color, rowBg || qCell.backgroundColor)
        report.measurements.push({
          view: 'H04-queue-selected-hover',
          theme,
          lang,
          ratio,
          cellColor: qCell.color,
          rowBg,
          pointerHover: true,
          ...qCell,
        })
        if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H04', theme, lang, ratio })
        if (theme === 'light' && qCell.color === 'rgb(32, 32, 30)' && rowBg?.includes('232, 241, 252')) {
          pushIssue(report, { id: 'H04', theme, lang, detail: 'cell not inheriting accent foreground on selected row' })
        }
      }
      const h04Shot = join(OUT, `b1-closure-queue-${tag}.png`)
      await page.screenshot({ path: h04Shot, fullPage: false })
      report.captures.push(h04Shot)
    } else {
      pushIssue(report, { id: 'H04', theme, lang, detail: 'no selected queue row' })
    }

    // H05 sidebar inactive hover vs active default
    const intakeBtn = page.locator('[data-sidebar="menu-button"]').nth(0)
    await intakeBtn.hover()
    await page.waitForTimeout(200)
    const hoverSidebar = await measure(page, '[data-sidebar="menu-button"]:hover')
    const activeSidebar = await measure(page, '[data-sidebar="menu-button"][data-active="true"]')
    report.measurements.push({ view: 'H05-sidebar-hover', theme, lang, pointerHover: true, ...hoverSidebar })
    report.measurements.push({ view: 'H05-sidebar-active', theme, lang, ...activeSidebar })
    if (hoverSidebar && activeSidebar && hoverSidebar.backgroundColor === activeSidebar.backgroundColor) {
      pushIssue(report, { id: 'H05', theme, lang, detail: 'inactive hover bg equals active bg' })
    }
    const h05Shot = join(OUT, `b1-closure-sidebar-${tag}.png`)
    await page.screenshot({ path: h05Shot, fullPage: false })
    report.captures.push(h05Shot)

    // H06 escalations empty
    await page.evaluate(() => {
      const cards = [...document.querySelectorAll('[data-slot="card"]')]
      const esc = cards.find((c) => {
        const t = c.textContent?.toLowerCase() || ''
        return t.includes('escalat') || t.includes('تصعيد')
      })
      esc?.scrollIntoView({ block: 'center' })
    })
    await page.waitForTimeout(300)
    const emptyIcon = await measure(page, '[data-slot="empty-icon"]')
    const emptyIconBg = await effectiveBg(page, '[data-slot="empty-icon"]')
    if (emptyIcon) {
      const ratio = await contrastRatio(page, emptyIcon.color, emptyIconBg || emptyIcon.backgroundColor)
      report.measurements.push({ view: 'H06-escalations-empty-icon', theme, lang, ratio, bg: emptyIconBg, ...emptyIcon })
      if (emptyIconBg?.includes('232, 241, 252') && theme === 'dark') {
        pushIssue(report, { id: 'H06', theme, lang, detail: 'empty icon light chip in dark' })
      }
      if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'H06', theme, lang, ratio })
    } else {
      pushIssue(report, { id: 'H06', theme, lang, detail: 'empty-icon not found' })
    }
    const h06Shot = join(OUT, `b1-closure-escalations-${tag}.png`)
    await page.screenshot({ path: h06Shot, fullPage: false })
    report.captures.push(h06Shot)

    // E01 explore lens
    await page.locator('[data-sidebar="menu-button"]').nth(2).click()
    await page.waitForTimeout(2500)
    const lensText = await measure(page, 'button .relative.z-10')
    const lensBgEl = await measure(page, 'button .absolute.inset-0.rounded-md.bg-primary')
    if (lensText && lensBgEl) {
      const ratio = await contrastRatio(page, lensText.color, lensBgEl.backgroundColor)
      report.measurements.push({
        view: 'E01-explore-lens',
        theme,
        lang,
        ratio,
        textColor: lensText.color,
        pillBg: lensBgEl.backgroundColor,
        fontSize: lensText.fontSize,
        fontWeight: lensText.fontWeight,
      })
      if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'E01', theme, lang, ratio })
    } else if (theme === 'dark') {
      pushIssue(report, { id: 'E01', theme, lang, detail: 'lens pill selectors missing' })
    }
    const e01Shot = join(OUT, `b1-closure-explore-lens-${tag}.png`)
    await page.screenshot({ path: e01Shot, fullPage: false })
    report.captures.push(e01Shot)

    // E02 schema proxy — Force/Tree + 2D/3D selected controls
    const schemaLabel = lang === 'ar' ? 'المخطط' : 'Schema'
    await page.locator('button').filter({ hasText: new RegExp(schemaLabel, 'i') }).click().catch(() => {})
    await page.waitForTimeout(3500)
    const e02Force = await measure(page, 'button.bg-primary.text-primary-foreground')
    if (e02Force) {
      const ratio = await contrastRatio(page, e02Force.color, e02Force.backgroundColor)
      report.measurements.push({ view: 'E02-schema-selected', theme, lang, ratio, control: 'force-or-renderer', ...e02Force })
      if (ratio !== null && ratio < 4.5) pushIssue(report, { id: 'E02', theme, lang, ratio })
    } else {
      pushIssue(report, { id: 'E02', theme, lang, detail: 'no bg-primary selected control on schema' })
    }
    const e02Shot = join(OUT, `b1-closure-schema-${tag}.png`)
    await page.screenshot({ path: e02Shot, fullPage: false })
    report.captures.push(e02Shot)
  }
}

// Verdicts
const graphBlocked = report.endpoint.graph?.status !== 200
for (const id of ['H01', 'H02', 'H03', 'H04', 'H05', 'H06', 'E01', 'E02']) {
  const idIssues = report.issues.filter((i) => i.id === id)
  if (id === 'E02' && graphBlocked) {
    // Schema proxy measured; live graph still blocked
    report.verdicts[id] = idIssues.length ? 'FAIL' : 'PASS (schema proxy; live /graph BLOCKED)'
  } else {
    report.verdicts[id] = idIssues.length ? 'FAIL' : 'PASS'
  }
}

report.overall =
  report.issues.filter((i) => i.id !== 'BUILD').length === 0 ? 'PASS' : report.issues.some((i) => i.id === 'BUILD') ? 'BLOCKED' : 'FAIL'

writeFileSync(join(OUT, 'measurements-b1-closure.json'), JSON.stringify(report, null, 2))
await browser.close()
console.log('B1 closure issues:', report.issues.length, report.issues)
console.log('Verdicts:', report.verdicts)
console.log('Overall:', report.overall)
console.log('written', join(OUT, 'measurements-b1-closure.json'))
