/*
 * Phase 12 - real-browser end-to-end scenarios (contract F). Real Chromium against REAL backend processes.
 *
 *   E2E_MODULES=/tmp/pw LD_LIBRARY_PATH=/tmp/al/lib E2E_PYTHON=/tmp/av/bin/python node web/e2e/phase12_browser_e2e.cjs
 *
 * Needs: a running extractive server (E2E_URL, default http://127.0.0.1:8000) with web/dist built. The script itself starts two more real servers
 * (E2E_PORT_FAIL default 8011: `--generator ollama`, which really fails when Ollama is absent; E2E_PORT_KILL default 8012: killed mid-session).
 * The generator-failure scenario is a failure-path test and NOT an LLM evaluation. The "renderer" checks at the end use a clearly labelled
 * SYNTHETIC response (request interception) because the extractive generator never emits code spans, bold text or long answers; they test the
 * markdown renderer only and are reported separately from the backend scenarios. Output: data/phase12/browser_e2e.json, data/phase12/screens/*.png
 */
const path = require('path')
const fs = require('fs')
const { spawn } = require('child_process')
const modDir = process.env.E2E_MODULES || process.cwd()
const req = (m) => require(require.resolve(m, { paths: [modDir] }))
const puppeteer = req('puppeteer-core')
const BASE = process.env.E2E_URL || 'http://127.0.0.1:8000'
const PORT_FAIL = process.env.E2E_PORT_FAIL || '8011'
const PORT_KILL = process.env.E2E_PORT_KILL || '8012'
const PY = process.env.E2E_PYTHON || 'python3'
const ROOT = path.resolve(__dirname, '../..')
const OUT = path.join(ROOT, 'data/phase12')
fs.mkdirSync(path.join(OUT, 'screens'), { recursive: true })

const checks = []
const check = (name, ok, detail, group = 'backend') => { checks.push({ name, group, passed: !!ok, detail: detail ?? null }); console.log(`${ok ? 'PASS' : 'FAIL'}  [${group}] ${name}${detail ? '  - ' + String(detail).slice(0, 160) : ''}`) }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const ABSTAIN = "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail."

async function api(base, message) {
  const r = await fetch(`${base}/api/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ message }) })
  return { http: r.status, body: await r.json() }
}
async function ask(page, text, selector) {
  const before = await page.$$eval('[data-testid="assistant-message"]', (n) => n.length)
  await page.click('textarea')
  await page.keyboard.type(text)
  await page.keyboard.press('Enter')
  await page.waitForFunction((n) => document.querySelectorAll('[data-testid="assistant-message"]').length > n && !document.querySelector('[data-testid="loading"]'), { timeout: 40000 }, before)
  if (selector) await page.waitForSelector(selector, { timeout: 5000 })
}
const lastMsg = (page) => page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).innerText.replace(/\s+/g, ' ').trim())
const shot = (page, name) => page.screenshot({ path: path.join(OUT, 'screens', name) })
async function waitHealth(base, ms = 90000) {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) { try { const r = await fetch(`${base}/api/health`); if (r.ok) return true } catch (e) { /* not up yet */ } await sleep(1000) }
  return false
}
function startServer(port, generator) {
  const p = spawn(PY, ['scripts/rag_api.py', '--generator', generator, '--host', '127.0.0.1', '--port', port], { cwd: ROOT, env: { ...process.env, HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1', PYTHONDONTWRITEBYTECODE: '1' }, stdio: 'ignore' })
  return p
}
const strip = (a) => a.replace(/\s*\[S\d+\]/g, '').replace(/\s+/g, ' ').trim()

;(async () => {
  let executablePath = process.env.CHROMIUM_PATH
  let args = ['--no-sandbox', '--disable-dev-shm-usage']
  if (!executablePath) { const cm = req('@sparticuz/chromium'); const chromium = cm.default || cm; executablePath = await chromium.executablePath(); args = [...chromium.args, '--no-sandbox'] }
  const browser = await puppeteer.launch({ args, executablePath, headless: 'shell' })
  const consoleErrors = []
  // pages of the deliberate failure scenarios (generator 502, killed server) are not console-tracked: the browser logs the failed requests by design
  const newPage = async (url, w = 1280, h = 800, opts = {}, track = true) => {
    const p = await browser.newPage()
    if (track) {
      p.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()) })
      p.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))
    }
    await p.setViewport({ width: w, height: h, ...opts })
    await p.goto(url + '/', { waitUntil: 'networkidle0' })
    return p
  }
  const children = []
  try {
    // ---- 1. normal answer: displayed text and citations equal the API response
    const page = await newPage(BASE)
    const q1 = 'Which transaction is used to monitor meter reading results?'
    await ask(page, q1, '.prose-chat')
    const api1 = (await api(BASE, q1)).body
    const shown = await page.$eval('.prose-chat', (e) => { const c = e.cloneNode(true); c.querySelectorAll('.cite-chip').forEach((x) => x.remove()); return c.textContent.replace(/\s+/g, ' ').trim() })
    check('normal answer: displayed text equals the API answer (citation markers aside)', api1.status === 'answered' && strip(shown) === strip(api1.answer), strip(api1.answer).slice(0, 80))
    const hrefs = await page.$$eval('[data-testid="source-item"] a', (a) => a.map((x) => x.href))
    check('normal answer: every displayed citation URL is byte-equal to an API source URL', hrefs.length > 0 && hrefs.every((h) => api1.sources.some((s) => s.url === h)), hrefs[0])
    check('normal answer: citation links open safely in a new tab', await page.$$eval('[data-testid="source-item"] a', (a) => a.every((x) => x.target === '_blank' && x.rel.includes('noopener'))))
    // ---- 2. citation chip -> its source item becomes the active one
    const chips = await page.$$('.prose-chat .cite-chip')
    check('citation: the answer shows citation chips', chips.length > 0)
    if (chips.length) {
      await chips[0].click(); await sleep(150)
      const active = await page.$$eval('[data-testid="source-item"]', (n) => n.filter((x) => /border-accent/.test(x.className)).length)
      check('citation: clicking a chip highlights exactly one source item', active === 1, `active=${active}`)
    }
    await shot(page, 'p12_01_answer_desktop.png')
    // ---- 3. abstention (absent detail) shows the exact message, no sources, not framed as an answer
    await ask(page, 'What is the minimum installment amount?', '[data-status="unable_to_verify"]')
    const abst = await page.$$eval('[data-status="unable_to_verify"]', (n) => n.at(-1).innerText)
    check('abstention: exact abstention message', abst.includes(ABSTAIN))
    check('abstention: no "here\'s what I found", no sources, no citation chips', !/here'?s what i found/i.test(abst) && (await page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).querySelectorAll('[data-testid="source-item"], .cite-chip').length)) === 0)
    // ---- 4. out of domain
    await ask(page, 'What is the weather in Hyderabad?', '[data-status="out_of_scope"]')
    check('out of domain: labelled and not answered', /Out of scope/i.test(await page.$eval('[data-status="out_of_scope"]', (e) => e.innerText)))
    // ---- 5. page not ingested
    await ask(page, 'How are dunning notices created?', '[data-status="documentation_unavailable"]')
    const dn = await page.$eval('[data-status="documentation_unavailable"]', (e) => e.innerText)
    check('page not ingested: "documentation unavailable" wording, a reference-only link, no sources', /not currently available/.test(dn) && /Reference only/.test(dn) && (await page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).querySelectorAll('[data-testid="source-item"]').length)) === 0)
    // ---- 6. unresolved identity
    await ask(page, 'What is a business partner?')
    const unv = await lastMsg(page)
    check('unresolved identity: stated plainly, no card ids', unv.includes("I couldn't verify the relevant documentation.") && !/M2C-\d+/.test(unv))
    check('no raw card ids anywhere in the conversation', !/M2C-\d+/.test(await page.evaluate(() => document.body.innerText)))
    // ---- 7. list rendering from a real extractive answer
    await ask(page, 'How does invoicing create the link to contract accounting?', '.prose-chat')
    const r7 = (await api(BASE, 'How does invoicing create the link to contract accounting?')).body
    const hasBullets = /(^|\n)[-*] /.test(r7.answer || '')
    const lis = await page.$$eval('[data-testid="assistant-message"]', (n) => n.at(-1).querySelectorAll('li').length)
    check('list rendering: a bulleted API answer renders as list items', hasBullets ? lis >= 2 : true, hasBullets ? `li=${lis}` : 'this answer has no bullets (not exercised)')
    // ---- 8. conversation continuity: second question in the same conversation, history survives a reload
    const n0 = await page.$$eval('[data-testid="user-message"]', (n) => n.length)
    await page.reload({ waitUntil: 'networkidle0' })
    check('continuity: the conversation is kept in the history list after a reload', (await page.$$('nav[aria-label="Chat history"] li')).length === 1)
    await page.evaluate(() => document.querySelector('nav[aria-label="Chat history"] li > button:first-child').click())
    await page.waitForSelector('[data-testid="assistant-message"]')
    const n1 = await page.$$eval('[data-testid="user-message"]', (n) => n.length)
    check('continuity: reopening it restores all stored messages', n0 > 1 && n1 === n0, `${n0} -> ${n1}`)
    await ask(page, 'How is billing handled?', '.prose-chat')
    check('continuity: a further question is appended to the same conversation (still one history entry)', (await page.$$eval('[data-testid="user-message"]', (n) => n.length)) === n1 + 1 && (await page.$$('nav[aria-label="Chat history"] li')).length === 1)
    await page.close()

    // ---- 9. mobile layout with a real answer and a real abstention
    const mob = await newPage(BASE, 390, 844, { isMobile: true, hasTouch: true, deviceScaleFactor: 2 })
    await ask(mob, 'How is billing handled?', '.prose-chat')
    await ask(mob, 'What is the minimum installment amount?', '[data-status="unable_to_verify"]')
    const ov = await mob.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    check('mobile: no horizontal overflow with an answer and an abstention on screen', ov <= 0, `overflow ${ov}px`)
    await shot(mob, 'p12_02_mobile.png')
    await mob.close()

    // ---- 10. generator failure: a REAL server with --generator ollama (Ollama is really absent here) -> failure-path test, not an LLM evaluation
    const failSrv = startServer(PORT_FAIL, 'ollama'); children.push(failSrv)
    const failBase = `http://127.0.0.1:${PORT_FAIL}`
    check('generator-failure server started', await waitHealth(failBase), failBase)
    const g = await newPage(failBase, 1280, 800, {}, false)
    await ask(g, q1, '[data-testid="error-message"]')
    const gm = await g.$eval('[data-testid="error-message"]', (e) => e.innerText)
    check('generator failure: the user sees an actionable error and NO answer text (no silent fallback to another generator)', /answer generator failed/i.test(gm) && (await g.$$('.prose-chat')).length === 0, gm.slice(0, 100))
    await ask(g, 'What is the weather in Hyderabad?', '[data-status="out_of_scope"]')
    const oos = await g.$eval('[data-status="out_of_scope"]', (e) => e.innerText)
    check('generator failure server: a question that never reaches generation (out of domain) is still answered honestly', /doesn't appear to match/.test(oos), oos.slice(0, 80))
    await shot(g, 'p12_03_generator_failure.png')
    await g.close()

    // ---- 11. backend failure: a REAL server process is killed mid-session
    const killSrv = startServer(PORT_KILL, 'extractive'); children.push(killSrv)
    const killBase = `http://127.0.0.1:${PORT_KILL}`
    check('disposable server started', await waitHealth(killBase), killBase)
    const k = await newPage(killBase, 1280, 800, {}, false)
    await ask(k, 'How is billing handled?', '.prose-chat')
    killSrv.kill('SIGKILL'); await sleep(1500)
    await ask(k, 'How are devices managed?', '[data-testid="error-message"]')
    const km = await k.$eval('[data-testid="error-message"]', (e) => e.innerText)
    check('backend killed mid-session: the user sees an actionable "unable to reach" message; the earlier answer stays visible', /Unable to reach the RAG service/.test(km) && (await k.$$('.prose-chat')).length === 1, km.slice(0, 100))
    await shot(k, 'p12_04_backend_killed.png')
    await k.close()

    // ---- 12. RENDERER checks with a SYNTHETIC response (labelled): long answer, code span, bold, ordered list, numeric value
    const long = Array.from({ length: 30 }, (_, i) => `Sentence ${i + 1} of a deliberately long synthetic answer that must wrap instead of overflowing the layout [S1].`).join(' ')
    const synth = { schema_version: '11.1', conversation_id: 'c', status: 'answered', answer: `Use transaction \`EL31\` and set the value to **0.5**.\n\n1. First step [S1]\n2. Second step\n\n\`\`\`\nEL31 --long-code-line-that-should-scroll-horizontally-inside-its-own-block-and-not-widen-the-page-0123456789\n\`\`\`\n\n${long}`,
      sources: [{ marker: 'S1', title: 'Synthetic', url: 'https://example.invalid/x', section: 'A', chunk_id: 'x' }], topic_reference: null, metadata: { card_id: null, grounded: true, generator: 'synthetic' } }
    const s = await browser.newPage(); await s.setViewport({ width: 390, height: 844, isMobile: true })
    s.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message))
    await s.setRequestInterception(true)
    s.on('request', (r) => (r.url().includes('/api/chat') ? r.respond({ status: 200, contentType: 'application/json', body: JSON.stringify(synth) }) : r.continue()))
    await s.goto(BASE + '/', { waitUntil: 'networkidle0' })
    await ask(s, 'synthetic renderer test', '.prose-chat')
    const R = await s.$eval('.prose-chat', (e) => ({ code: e.querySelectorAll('code').length, strong: e.querySelectorAll('strong').length, ol: e.querySelectorAll('ol li').length, pre: e.querySelectorAll('pre').length }))
    check('renderer (synthetic): inline code, bold, ordered list and code block render as elements', R.code >= 1 && R.strong === 1 && R.ol === 2 && R.pre === 1, JSON.stringify(R), 'renderer-synthetic')
    const ovs = await s.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    check('renderer (synthetic): a long answer and a long code line cause no horizontal page overflow on mobile', ovs <= 0, `overflow ${ovs}px`, 'renderer-synthetic')
    await shot(s, 'p12_05_renderer_synthetic.png')
    await s.close()

    check('no console errors or uncaught exceptions', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 300), 'all')
  } finally {
    for (const c of children) { try { c.kill('SIGKILL') } catch (e) { /* already gone */ } }
    await browser.close()
  }
  const passed = checks.filter((c) => c.passed).length
  fs.writeFileSync(path.join(OUT, 'browser_e2e.json'), JSON.stringify({ schema_version: 1, base_url: BASE, passed, total: checks.length, backend_checks: checks.filter((c) => c.group === 'backend').length, synthetic_checks: checks.filter((c) => c.group === 'renderer-synthetic').length, checks }, null, 1) + '\n')
  console.log(`\n${passed}/${checks.length} Phase 12 browser checks passed`)
  process.exit(passed === checks.length ? 0 : 1)
})().catch((e) => { console.error('phase12 browser e2e crashed:', e); process.exit(2) })
