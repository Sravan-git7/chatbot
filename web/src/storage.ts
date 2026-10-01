import type { Conversation, Settings } from './types'

const CONV_KEY = 'sapchat.v1.conversations'
const SET_KEY = 'sapchat.v1.settings'

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(CONV_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((c) => c && typeof c.id === 'string' && Array.isArray(c.messages))
      .map((c: Conversation) => ({
        ...c,
        // a request that was in flight when the page closed can never complete: say so instead of leaving a spinner
        messages: c.messages.map((m) => (m.pending ? { ...m, pending: false, error: { kind: 'offline' as const, code: 'interrupted', message: 'This request was interrupted when the page was closed. Ask the question again.' } } : m)),
      }))
  } catch {
    return []
  }
}

export function saveConversations(list: Conversation[]): boolean {
  // the debug block can be large and is only meaningful live: it is not persisted
  const slim = list.map((c) => ({ ...c, messages: c.messages.map((m) => (m.result?.debug ? { ...m, result: { ...m.result, debug: null } } : m)) }))
  try {
    localStorage.setItem(CONV_KEY, JSON.stringify(slim))
    return true
  } catch {
    return false
  }
}

export function loadSettings(): Settings {
  try {
    const s = JSON.parse(localStorage.getItem(SET_KEY) ?? '{}')
    return { developerMode: s?.developerMode === true }
  } catch {
    return { developerMode: false }
  }
}

export function saveSettings(s: Settings): void {
  try {
    localStorage.setItem(SET_KEY, JSON.stringify(s))
  } catch {
    /* storage unavailable: settings last for this session only */
  }
}

export function newId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c?.randomUUID) return c.randomUUID().replace(/-/g, '')
  return Array.from({ length: 32 }, () => Math.floor(Math.random() * 16).toString(16)).join('')
}

export function titleFrom(text: string): string {
  const t = text.replace(/\s+/g, ' ').trim()
  return t.length > 48 ? `${t.slice(0, 47)}…` : t || 'New chat'
}
