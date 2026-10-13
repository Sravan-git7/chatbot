// New local browser smoke: does not overwrite sealed historical Playwright reports.
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const outIndex = process.argv.indexOf('--out')
if (outIndex < 0) throw new Error('--out is required (new result path)')
const output = path.resolve(process.argv[outIndex + 1])
const result = { status: 'FAIL', checks: [], browser: 'chromium' }
const port = 8347
const base = `http://127.0.0.1:${port}`
let server, browser
let code = 1
try {
  const binary = chromium.executablePath()
  if (!fs.existsSync(binary)) {
    result.status = 'BLOCKED'
    result.reason = 'Chromium browser binaries are not installed; no browser E2E executed.'
    code = 2
  } else {
    const python = process.env.SURA_PYTHON || (process.platform === 'win32'
      ? path.join(root, 'av/Scripts/python.exe') : path.join(root, '.venv/bin/python'))
    server = spawn(python, ['scripts/rag_api.py', '--host', '127.0.0.1', '--port', String(port), '--generator', 'extractive'],
      { cwd: root, stdio: 'ignore', env: { ...process.env, RAG_ENABLE_DEBUG: '0' } })
    let ready = false
    for (let attempt = 0; attempt < 180; attempt++) {
      try { if ((await fetch(`${base}/ready`)).ok) { ready = true; break } } catch {}
      if (server.exitCode !== null) throw new Error('Backend exited before readiness')
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!ready) throw new Error('Backend startup deadline expired')
    browser = await chromium.launch({ headless: true })
    const page = await browser.newPage()
    await page.goto(base)
    const message = page.getByRole('textbox', { name: 'Message' })
    const send = page.getByRole('button', { name: 'Send message' })
    await message.fill('How does billing work in SAP Utilities?')
    const pending = page.waitForResponse(r => r.url().endsWith('/api/chat') && r.request().method() === 'POST')
    await send.click()
    const response = await pending
    const body = await response.json()
    if (body.status !== 'answered' || !body.metadata.grounded || !body.sources.length) throw new Error('Billing not grounded')
    await message.waitFor({ state: 'visible' })
    await page.waitForFunction(() => !document.querySelector('textarea').disabled)
    const visibleAnswer = body.answer.replace(/\[S\d+\]/g, '').split(/\n/)[0].trim().slice(0, 60)
    await page.getByRole('log', { name: 'Conversation' }).getByText(visibleAnswer, { exact: false }).first().waitFor()
    result.checks.push('live grounded answer rendered with verified sources')
    await page.route('**/api/chat', route => route.abort('failed'))
    await message.fill('How does dunning work?')
    await send.click()
    await page.waitForFunction(() => !document.querySelector('textarea').disabled)
    result.checks.push('network failure releases composer')
    await page.unroute('**/api/chat')
    await message.fill('How does dunning work?')
    const recovery = page.waitForResponse(r => r.url().endsWith('/api/chat') && r.request().method() === 'POST')
    await send.click()
    const recovered = await (await recovery).json()
    if (recovered.status !== 'answered' || !recovered.metadata.grounded) throw new Error('Recovery failed')
    result.checks.push('recovery after network failure')
    result.status = 'PASS'
    code = 0
  }
} catch (error) {
  result.reason = `${error.name}: ${error.message}`
} finally {
  if (browser) await browser.close()
  if (server) server.kill()
  fs.mkdirSync(path.dirname(output), { recursive: true })
  fs.writeFileSync(output, JSON.stringify(result, null, 2))
}
console.log(JSON.stringify(result, null, 2))
process.exitCode = code
