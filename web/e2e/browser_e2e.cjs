/*
 * Phase 11 - real-browser end-to-end check of the built UI against the RUNNING backend (no mocks, no stubbed fetch).
 *
 *   python scripts/rag_api.py --generator extractive --port 8000         # serves API + web/dist
 *   cd web && npm run build
 *   E2E_MODULES=/path/with/puppeteer-core CHROMIUM_PATH=/path/to/chrome node e2e/browser_e2e.cjs
 *
 * puppeteer-core is deliberately NOT a dependency of the project: install it (and a Chromium) wherever you run this check.
 * If CHROMIUM_PATH is unset, @sparticuz/chromium from E2E_MODULES is used. Output: data/phase11/browser_e2e.json and data/phase11/screens/*.png
 */
const path = require('path')
const fs = require('fs')
const modDir = process.env.E2E_MODULES || process.cwd()
const req = (m) => require(require.resolve(m, { paths: [modDir] }))
const puppeteer = req('puppeteer-core')
const BASE = process.env.E2E_URL || 'http://127.0.0.1:8000'
const OUT = path.resolve(__dirname, '../../data/phase11')
fs.mkdirSync(path.join(OUT, 'screens'), { recursive: true })

const checks = []
const check = (name, ok, detail) => { checks.push({ name, passed: !!ok, detail: detail ?? null }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  - ' + detail : ''}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function api(message) {
  const r = await fetch(`${BASE}/api/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message }) })
  return r.json()
}
async function ask(page, text, selector) {
  const before = await page.$$eval('[data-testid="assistant-message"]', (n) => n.length)
  await page.click('textarea')
  await page.keyboard.type(text)
  await page.keyboard.press('Enter')
  await page.waitForFunction((n) => document.querySelectorAll('[data-testid="assistant-message"]').length > n && !document.querySelector('[data-testid="loading"]'), { timeout: 30000 }, before)
  if (selector) await page.waitForSelector(selector, { timeout: 5000 })
}
const clickText = (page, t) => page.evaluate((t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t).click(), t)
const text = (page, sel) => page.$eval(sel, (e) => e.textContent)
const shot = (page, name) => page.screenshot({ path: path.join(OUT, 'screens', name) })

;(async () => {
  let executablePath = process.env.CHROMIUM_PATH
  let args = ['--no-sandbox', '--disable-dev-shm-usage']
  if (!executablePath) {
    const cm = req('@sparticuz/chromium'); const chromium = cm.default || cm
    executablePath = await chromium.executablePath()
    args = [...chromium.args, '--no-sandbox']
  }
  const browser = await puppeteer.launch({ args, executablePath, headless: 'shell' })
  const consoleErrors = []
  const page = await browser.newPage()
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))
  await page.setViewport({ width: 1280, height: 800 })

  // ---- initial load
  const t0 = Date.now()
  await page.goto(BASE + '/', { waitUntil: 'networkidle0' })
  const loadMs = Date.now() - t0
  const timing = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0]
    const fcp = performance.getEntriesByName('first-contentful-paint')[0]
    const res = performance.getEntriesByType('resource').filter((r) => !r.name.includes('/api/'))
    return { domContentLoaded: Math.round(nav.domContentLoadedEventEnd), load: Math.round(nav.loadEventEnd), fcp: fcp ? Math.round(fcp.startTime) : null, transferBytes: res.reduce((a, r) => a + (r.transferSize || 0), 0) + (nav.transferSize || 0), requests: res.length + 1 }
  })
  check('welcome heading renders', (await text(page, 'h1')) === 'Ask about SAP Utilities documentation.')
  const liveHealth = await page.evaluate(async () => (await (await fetch('/api/health')).json()))
  const coverageText = await text(page, '[data-testid="coverage"]')
  check(
    'coverage line reflects the live /api/health response',
    liveHealth.ready && coverageText.includes(`Currently ${liveHealth.pages_available} of ${liveHealth.topics} documentation sources are available.`),
    coverageText,
  )
  await shot(page, '01_welcome_desktop.png')

  // ---- example prompt -> real answer -> real citation
  const exampleText = 'How do I create an installment plan?'
  await page.evaluate((t) => [...document.querySelectorAll('button')].find((b) => b.textContent === t).click(), exampleText)
  await page.waitForSelector('[data-testid="assistant-message"] .prose-chat', { timeout: 30000 })
  const expected = await api(exampleText)
  const shownAnswer = await page.$eval('.prose-chat', (e) => e.innerText.replace(/\s+/g, ' ').trim())
  const firstSentence = expected.answer.split('\n')[0].replace(/\s*\[S\d+\]\s*$/, '').trim()
  check('example prompt reaches the backend and the answer text is displayed', shownAnswer.includes(firstSentence.slice(0, 60)), firstSentence.slice(0, 60))
  const hrefs = await page.$$eval('[data-testid="source-item"] a', (a) => a.map((x) => x.href))
  check('displayed citation URL is byte-equal to the URL returned by the API', hrefs.length > 0 && hrefs.every((h) => expected.sources.some((s) => s.url === h)), hrefs[0])
  check('citation link opens in a new tab safely', await page.$eval('[data-testid="source-item"] a', (a) => a.target === '_blank' && a.rel.includes('noopener')))
  check('citation chips are present in the answer', (await page.$$('.prose-chat .cite-chip')).length > 0)
  await shot(page, '02_answer_desktop.png')

  // ---- Shift+Enter keeps a newline, Enter sends
  await page.click('textarea')
  await page.keyboard.type('line one')
  await page.keyboard.down('Shift'); await page.keyboard.press('Enter'); await page.keyboard.up('Shift')
  await page.keyboard.type('line two')
  const ta = await page.$eval('textarea', (e) => e.value)
  check('Shift+Enter inserts a newline and does not send', ta === 'line one\nline two' && (await page.$$('[data-testid="user-message"]')).length === 1)
  await page.evaluate(() => { const t = document.querySelector('textarea'); t.focus() })
  await page.keyboard.press('Enter')
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="assistant-message"]').length === 2 && !document.querySelector('[data-testid="loading"]'), { timeout: 30000 })
  check('Enter sends the multi-line message', (await page.$$eval('[data-testid="user-message"]', (n) => n.at(-1).innerText)).includes('line one'))

  // ---- documentation unavailable / out of scope
  await ask(page, 'How are dunning notices created?', '[data-status="documentation_unavailable"]')
  const note = await text(page, '[data-status="documentation_unavailable"]')
  check('missing page is reported honestly with a reference link and no sources', /not currently available/.test(note) && /Reference only/.test(note))
  check('no raw card ids visible in the conversation', !/M2C-\d+/.test(await page.evaluate(() => document.body.innerText)))
  const refHref = await page.$eval('[aria-label="Related SAP Help topic"] a', (a) => a.href)
  const dun = await api('How are dunning notices created?')
  check('reference link equals the stored URL from the API', refHref === dun.topic_reference.url)
  await shot(page, '03_unavailable_desktop.png')
  await ask(page, 'What is the weather in Hyderabad?', '[data-status="out_of_scope"]')
  check('out-of-scope question is labelled and not answered', /Out of scope/i.test(await text(page, '[data-status="out_of_scope"]')))

  // ---- Phase 11.1: an absent detail is an abstention, not a related answer; an unverifiable identity is stated as such
  await ask(page, 'What is the minimum installment amount?', '[data-status="unable_to_verify"]')
  const abst = await page.$$eval('[data-status="unable_to_verify"]', (n) => n.at(-1).innerText)
  check('absent detail shows the exact abstention message', abst.includes("I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail."))
  check('abstention is not framed as an answer and shows no citation chips or sources', !/here'?s what i found/i.test(abst) && (await page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).querySelectorAll('[data-testid="source-item"]').length)) === 0)
  await ask(page, 'What is a business partner?')
  const unv = await page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).innerText)
  check('unresolved identity is stated plainly', unv.includes("I couldn't verify the relevant documentation.") && !/M2C-\d+/.test(unv))

  // ---- XSS through the question text
  await page.evaluate(() => { window.__xss = 0 })
  await ask(page, '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script> How is billing handled?')
  check('HTML typed by the user is displayed as text and never executed', (await page.evaluate(() => window.__xss)) === 0 && (await page.$$('[role="log"] img, [role="log"] script')).length === 0)

  // ---- conversations: switching, persistence across reload, delete
  const titlesBefore = await page.$$eval('nav[aria-label="Chat history"] li > button:first-child', (b) => b.length)
  await clickText(page, 'New chat')
  check('New chat returns to the welcome state', (await text(page, 'h1')) === 'Ask about SAP Utilities documentation.')
  await ask(page, 'How are devices managed?', '.prose-chat')
  const titles = await page.$$eval('nav[aria-label="Chat history"] li > button:first-child', (b) => b.length)
  check('a second conversation appears in the history', titles === titlesBefore + 1, `${titlesBefore} -> ${titles}`)
  await page.reload({ waitUntil: 'networkidle0' })
  check('conversations survive a reload (local storage)', (await page.$$('nav[aria-label="Chat history"] li')).length === titles)
  await page.evaluate(() => document.querySelectorAll('nav[aria-label="Chat history"] li > button:first-child')[1].click())
  await page.waitForSelector('[data-testid="assistant-message"]')
  check('selecting an old conversation shows its stored messages', (await page.$$('[data-testid="user-message"]')).length >= 1)

  // ---- developer mode
  check('developer panel is off by default', (await page.$('[data-testid="debug-panel"]')) === null)
  await page.evaluate(() => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Settings')).click())
  await page.waitForSelector('[role="dialog"]')
  await page.click('input[type="checkbox"]')
  check('about panel reports the live service state', /ready/.test(await text(page, '[data-testid="service-info"]')) && /extractive/.test(await text(page, '[data-testid="service-info"]')))
  await page.keyboard.press('Escape')
  await clickText(page, 'New chat')
  await ask(page, 'Which transaction is used to monitor meter reading results?', '[data-testid="debug-panel"]')
  await page.evaluate(() => document.querySelector('[data-testid="debug-panel"] summary').click())
  const dbgText = await text(page, '[data-testid="debug-panel"]')
  check('developer panel shows routing, grounding and latency from the backend', /M2C-07/.test(dbgText) && /grounding/.test(dbgText) && /latency/.test(dbgText))
  await shot(page, '04_debug_desktop.png')

  // ---- mobile layout
  const mob = await browser.newPage()
  await mob.setViewport({ width: 390, height: 844, isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
  await mob.goto(BASE + '/', { waitUntil: 'networkidle0' })
  check('mobile: sidebar is closed on load', (await mob.$eval('[data-testid="sidebar"]', (e) => getComputedStyle(e).display)) === 'none')
  await shot(mob, '05_welcome_mobile.png')
  await mob.click('button[aria-label="Open sidebar"]')
  check('mobile: sidebar opens as a drawer', (await mob.$eval('[data-testid="sidebar"]', (e) => getComputedStyle(e).display)) !== 'none')
  await mob.click('[data-testid="scrim"]', { offset: { x: 360, y: 400 } }).catch(() => {})
  await sleep(150)
  await ask(mob, 'How is billing handled?', '.prose-chat')
  const overflow = await mob.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  check('mobile: no horizontal overflow with an answer on screen', overflow <= 0, `overflow ${overflow}px`)
  await shot(mob, '06_answer_mobile.png')
  await mob.close()

  // ---- backend failure as seen by the user (network failure injected in the browser)
  const off = await browser.newPage()
  await off.setViewport({ width: 1280, height: 800 })
  await off.setRequestInterception(true)
  off.on('request', (r) => (r.url().includes('/api/chat') ? r.abort('connectionrefused') : r.continue()))
  await off.goto(BASE + '/', { waitUntil: 'networkidle0' })
  await ask(off, 'How is billing handled?', '[data-testid="error-message"]')
  check('network failure shows an actionable message', /Unable to reach the RAG service/.test(await text(off, '[data-testid="error-message"]')))
  await shot(off, '07_error_desktop.png')
  await off.close()

  check('no console errors or uncaught exceptions', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 300))
  await browser.close()
  const passed = checks.filter((c) => c.passed).length
  const result = { schema_version: 1, base_url: BASE, passed, total: checks.length, checks, initial_load: { wall_ms_networkidle: loadMs, ...timing } }
  fs.writeFileSync(path.join(OUT, 'browser_e2e.json'), JSON.stringify(result, null, 1) + '\n')
  console.log(`\n${passed}/${checks.length} browser checks passed`)
  process.exit(passed === checks.length ? 0 : 1)
})().catch((e) => { console.error('browser e2e crashed:', e); process.exit(2) })
