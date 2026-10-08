import { describe, expect, it, vi } from 'vitest'
import { ApiError, OFFLINE_MESSAGE, fetchHealth, isChatResult, sendChat } from '../api'
import { json, result } from './helpers'

const catchErr = async (p: Promise<unknown>) => { try { await p } catch (e) { return e as ApiError } throw new Error('no error') }

describe('api client', () => {
  it('posts relative to /api/chat with the conversation id and debug flag', async () => {
    const f = vi.fn(async () => json(result()))
    vi.stubGlobal('fetch', f)
    await sendChat('hello', 'abc', true)
    const [url, init] = f.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/chat')
    expect(JSON.parse(String(init.body))).toEqual({ message: 'hello', conversation_id: 'abc', debug: true })
  })

  it('network failure -> offline error with the actionable message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const e = await catchErr(sendChat('q', 'c', false))
    expect(e.info).toMatchObject({ kind: 'offline', message: OFFLINE_MESSAGE })
  })

  it('timeout -> timeout error', async () => {
    vi.stubGlobal('fetch', vi.fn((_u: string, init: RequestInit) => new Promise((_res, rej) => { init.signal!.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError'))) })))
    const e = await catchErr(sendChat('q', 'c', false, { timeoutMs: 20 }))
    expect(e.info.kind).toBe('timeout')
    expect(e.info.message).toContain('did not answer')
  })

  it('API error envelope -> http error with a hint for the code', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ error: { code: 'service_not_ready', message: 'raw' } }, 503)))
    const e = await catchErr(sendChat('q', 'c', false))
    expect(e.info).toMatchObject({ kind: 'http', code: 'service_not_ready' })
    expect(e.info.message).toContain('stores')
  })

  it('validation error keeps the server detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => json({ error: { code: 'invalid_request', message: 'The message is empty.' } }, 422)))
    expect((await catchErr(sendChat('q', 'c', false))).info.message).toContain('The message is empty.')
  })

  it('non-JSON error body -> unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('<html>Bad gateway</html>', { status: 502 })))
    expect((await catchErr(sendChat('q', 'c', false))).info.kind).toBe('offline')
  })

  it('shape validation accepts the distinct exhausted-elaboration status', () => {
    const exhausted = result({
      status: 'no_additional_verified_evidence',
      answer: "That's all the additional detail I could verify from the available documentation.",
      sources: [],
      metadata: { ...result().metadata, grounded: false, can_elaborate: false, reason_code: 'NO_ADDITIONAL_SUPPORTED_DETAILS' },
    })
    expect(isChatResult(exhausted)).toBe(true)
    expect(isChatResult({ ...result(), status: 'maybe' })).toBe(false)
    expect(isChatResult({ ...result(), metadata: undefined })).toBe(false)
    expect(isChatResult({ ...result(), sources: [{ url: 5 }] })).toBe(false)
    expect(isChatResult(null)).toBe(false)
  })

  it('health returns null when the service cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('x') }))
    expect(await fetchHealth()).toBeNull()
  })
})
