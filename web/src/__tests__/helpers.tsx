import { vi } from 'vitest'
import type { ChatContext, ChatResult, Health, Source } from '../types'

export const HEALTH: Health = { status: 'ok', ready: true, generator: 'extractive', topics: 29, pages_available: 25, debug_enabled: true }

export const SOURCE: Source = {
  type: 'page', marker: 'S1', title: 'Creating Installment Plans', section: 'Creating Installment Plans > Activities',
  url: 'https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/x/y.html', source_id: 'M2C-24', chunk_id: 'g/p/001',
}

export function result(over: Partial<ChatResult> = {}): ChatResult {
  return {
    schema_version: '11.1', conversation_id: 'c', status: 'answered', answer: 'Choose Account > Installment Plan > Create. [S1]\nA plan has an interval. [S1]',
    sources: [SOURCE], topic_reference: null,
    metadata: { card_id: 'M2C-24', card_title: 'Creating Installment Plans', identity_status: 'identified_not_local', page_available: true, generator: 'extractive', grounded: true, can_elaborate: true,
      grounding: { checked: true, ok: true, sentences: 2, violations: 0, cited_markers: ['S1'] }, pipeline_status: 'answered', reason_code: null, latency_ms: 12,
      topic_identity: { source_id: 'M2C-24', title: 'Creating Installment Plans', guide_id: 'guide-plan', page_id: 'page-plan', industry: 'SAP Utilities/IS-U' },
      follow_up_category: null },
    ...over,
  }
}

type Handler = (body: { message: string; conversation_id: string; debug: boolean; context?: ChatContext }) => Response | Promise<Response>

export const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

/** Replaces `fetch` for UI unit tests only; the full UI -> API -> RAG chain is exercised separately (web/e2e and scripts/phase11_e2e.py). */
export function stubBackend(chat: Handler, health: Health | null = HEALTH) {
  const calls: { message: string; conversation_id: string; debug: boolean; context?: ChatContext }[] = []
  const f = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/api/health')) {
      if (health === null) throw new TypeError('Failed to fetch')
      return json(health)
    }
    const body = JSON.parse(String(init?.body))
    calls.push(body)
    return chat(body)
  })
  vi.stubGlobal('fetch', f)
  return { calls, fetch: f }
}

export function mockMatchMedia(desktop: boolean) {
  vi.stubGlobal('matchMedia', (q: string) => ({
    matches: q.includes('min-width') ? desktop : false, media: q, addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {}, onchange: null, dispatchEvent: () => false,
  }))
}
