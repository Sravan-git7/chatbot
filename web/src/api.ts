import type { ChatError, ChatResult, Health } from './types'

const BASE = (import.meta.env?.VITE_API_BASE as string | undefined) ?? ''
export const REQUEST_TIMEOUT_MS = 60_000
export const MAX_MESSAGE_CHARS = 2000
const STATUSES = ['answered', 'documentation_unavailable', 'unable_to_verify', 'out_of_scope']

export class ApiError extends Error {
  info: ChatError
  constructor(info: ChatError) {
    super(info.message)
    this.info = info
  }
}

export const OFFLINE_MESSAGE = 'Unable to reach the RAG service. Make sure the backend is running (python scripts/rag_api.py) and try again.'

const HTTP_HINTS: Record<string, string> = {
  generator_failed: 'The answer generator failed, so no answer was produced. If the backend is configured for Ollama, check that Ollama is running and the model is installed.',
  service_not_ready: 'The RAG service has not finished starting or its document stores are missing.',
  pipeline_failed: 'The retrieval pipeline failed while handling your question, so no answer was produced.',
  invalid_request: 'The request was not accepted.',
  payload_too_large: 'The message is too large to send.',
  debug_disabled: 'Developer details are disabled on this server.',
}

/** Runtime check of the response shape: a malformed body is reported, never rendered. */
export function isChatResult(x: unknown): x is ChatResult {
  if (!x || typeof x !== 'object') return false
  const r = x as Record<string, unknown>
  const m = r.metadata as Record<string, unknown> | undefined
  return (
    typeof r.answer === 'string' &&
    typeof r.conversation_id === 'string' &&
    typeof r.status === 'string' && STATUSES.includes(r.status) &&
    Array.isArray(r.sources) &&
    r.sources.every((s) => !!s && typeof s === 'object' && (typeof (s as { url?: unknown }).url === 'string' || (s as { url?: unknown }).url === null)) &&
    !!m && typeof m === 'object' && typeof m.generator === 'string' && typeof m.grounded === 'boolean'
  )
}

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.json()
  } catch {
    return undefined
  }
}

export async function sendChat(
  message: string,
  conversationId: string,
  debug: boolean,
  opts: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<ChatResult> {
  const ctl = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => { timedOut = true; ctl.abort() }, opts.timeoutMs ?? REQUEST_TIMEOUT_MS)
  opts.signal?.addEventListener('abort', () => ctl.abort())
  let res: Response
  try {
    res = await fetch(`${BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, conversation_id: conversationId, debug }),
      signal: ctl.signal,
    })
  } catch {
    if (timedOut) {
      throw new ApiError({ kind: 'timeout', code: 'timeout', message: `The RAG service did not answer within ${Math.round((opts.timeoutMs ?? REQUEST_TIMEOUT_MS) / 1000)} seconds. It may be busy or stuck; try again.` })
    }
    throw new ApiError({ kind: 'offline', code: 'unreachable', message: OFFLINE_MESSAGE })
  } finally {
    clearTimeout(timer)
  }
  const body = await readJson(res)
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } } | undefined)?.error
    if (!err) {
      // a proxy (or nothing at all) answered instead of the backend
      throw new ApiError({ kind: 'offline', code: `http_${res.status}`, message: `${OFFLINE_MESSAGE} (HTTP ${res.status})` })
    }
    const code = err.code ?? `http_${res.status}`
    const hint = HTTP_HINTS[code]
    throw new ApiError({ kind: 'http', code, message: hint ? `${hint}${code === 'invalid_request' && err.message ? ` ${err.message}` : ''}` : err.message ?? `The service returned HTTP ${res.status}.` })
  }
  if (!isChatResult(body)) {
    throw new ApiError({ kind: 'malformed', code: 'malformed_response', message: 'The service returned a response this app could not understand, so nothing is shown. Check that the frontend and backend versions match.' })
  }
  return body
}

export async function fetchHealth(signal?: AbortSignal): Promise<Health | null> {
  try {
    const res = await fetch(`${BASE}/api/health`, { signal })
    const body = (await readJson(res)) as Health | undefined
    return body && typeof body.ready === 'boolean' ? body : null
  } catch {
    return null
  }
}
