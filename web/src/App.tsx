import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, fetchHealth, sendChat } from './api'
import AboutPanel from './components/AboutPanel'
import Composer from './components/Composer'
import MessageView from './components/MessageView'
import Sidebar from './components/Sidebar'
import Welcome from './components/Welcome'
import { loadConversations, loadSettings, newId, saveConversations, saveSettings, titleFrom } from './storage'
import type { ChatError, Conversation, Health, Message, Settings } from './types'

const DESKTOP_QUERY = '(min-width: 768px)'
const MIN_THINKING_MS = import.meta.env.MODE === 'test' ? 0 : 840

function useIsDesktop(): boolean {
  const get = () => (typeof window.matchMedia === 'function' ? window.matchMedia(DESKTOP_QUERY).matches : true)
  const [desktop, setDesktop] = useState(get)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(DESKTOP_QUERY)
    const on = () => setDesktop(mq.matches)
    mq.addEventListener?.('change', on)
    return () => mq.removeEventListener?.('change', on)
  }, [])
  return desktop
}

export default function App() {
  const desktop = useIsDesktop()
  const [conversations, setConversations] = useState<Conversation[]>(() => loadConversations())
  const [currentId, setCurrentId] = useState<string | null>(null)
  const [settings, setSettings] = useState<Settings>(() => loadSettings())
  const [health, setHealth] = useState<Health | null | undefined>(undefined)
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(desktop)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [storageWarning, setStorageWarning] = useState(false)
  const scroller = useRef<HTMLDivElement>(null)
  const settingsRef = useRef(settings)
  settingsRef.current = settings

  useEffect(() => {
    setSidebarOpen(desktop)
  }, [desktop])

  useEffect(() => {
    const ctl = new AbortController()
    fetchHealth(ctl.signal).then(setHealth)
    return () => ctl.abort()
  }, [])

  useEffect(() => {
    setStorageWarning(!saveConversations(conversations))
  }, [conversations])

  useEffect(() => {
    saveSettings(settings)
  }, [settings])

  const current = conversations.find((c) => c.id === currentId) ?? null
  const pending = !!current?.messages.some((m) => m.pending)

  useEffect(() => {
    const el = scroller.current
    if (el) {
      el.scrollTo?.({
        top: el.scrollHeight,
        behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
      })
    }
  }, [current?.messages.length, pending, currentId])

  const patchMessage = useCallback((convId: string, msgId: string, patch: Partial<Message>) => {
    setConversations((list) =>
      list.map((c) =>
        c.id === convId
          ? {
              ...c,
              updatedAt: Date.now(),
              messages: c.messages.map((m) => (m.id === msgId ? { ...m, ...patch } : m)),
            }
          : c,
      ),
    )
  }, [])

  const send = useCallback(
    async (text: string) => {
      const now = Date.now()
      const convId = currentId ?? newId()
      const user: Message = { id: newId(), role: 'user', content: text, createdAt: now }
      const reply: Message = { id: newId(), role: 'assistant', content: '', createdAt: now, pending: true }
      setConversations((list) => {
        const existing = list.find((c) => c.id === convId)
        if (existing) {
          return list.map((c) =>
            c.id === convId ? { ...c, updatedAt: now, messages: [...c.messages, user, reply] } : c,
          )
        }
        return [
          ...list,
          { id: convId, title: titleFrom(text), createdAt: now, updatedAt: now, messages: [user, reply] },
        ]
      })
      setCurrentId(convId)
      const startedAt = Date.now()
      try {
        const result = await sendChat(text, convId, settingsRef.current.developerMode)
        const elapsed = Date.now() - startedAt
        if (MIN_THINKING_MS > 0 && elapsed < MIN_THINKING_MS) {
          await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed))
        }
        patchMessage(convId, reply.id, { pending: false, content: result.answer, result, error: undefined })
      } catch (e) {
        const error: ChatError =
          e instanceof ApiError
            ? e.info
            : { kind: 'offline', code: 'unexpected', message: `Unexpected error: ${e instanceof Error ? e.message : String(e)}` }
        patchMessage(convId, reply.id, { pending: false, error })
      }
    },
    [currentId, patchMessage],
  )

  const retryMessage = useCallback(
    async (convId: string, replyId: string, questionText: string) => {
      if (!questionText.trim() || pending) return
      patchMessage(convId, replyId, { pending: true, error: undefined })
      const startedAt = Date.now()
      try {
        const result = await sendChat(questionText, convId, settingsRef.current.developerMode)
        const elapsed = Date.now() - startedAt
        if (MIN_THINKING_MS > 0 && elapsed < MIN_THINKING_MS) {
          await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed))
        }
        patchMessage(convId, replyId, { pending: false, content: result.answer, result, error: undefined })
      } catch (e) {
        const error: ChatError =
          e instanceof ApiError
            ? e.info
            : { kind: 'offline', code: 'unexpected', message: `Unexpected error: ${e instanceof Error ? e.message : String(e)}` }
        patchMessage(convId, replyId, { pending: false, error })
      }
    },
    [pending, patchMessage],
  )

  const select = (id: string) => {
    setCurrentId(id)
    if (!desktop) setSidebarOpen(false)
  }
  const startNew = () => {
    setCurrentId(null)
    if (!desktop) setSidebarOpen(false)
  }
  const remove = (id: string) => {
    setConversations((list) => list.filter((c) => c.id !== id))
    if (id === currentId) setCurrentId(null)
  }

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-surface text-stone-900">
      <Sidebar
        open={sidebarOpen}
        mobile={!desktop}
        conversations={conversations}
        currentId={currentId}
        onNew={startNew}
        onSelect={select}
        onDelete={remove}
        onToggle={() => setSidebarOpen((o) => !o)}
        onAbout={() => setAboutOpen(true)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-1 px-2 sm:px-3">
          {!sidebarOpen && (
            <>
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                aria-label="Open sidebar"
                aria-controls="sidebar"
                aria-expanded={false}
                className="rounded-lg p-2 text-stone-500 hover:bg-stone-200/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M4 7h16M4 12h16M4 17h16" />
                </svg>
              </button>
              <button
                type="button"
                onClick={startNew}
                aria-label="New chat"
                className="rounded-lg p-2 text-stone-500 hover:bg-stone-200/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              >
                <svg
                  width="20"
                  height="20"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M12 5v14M5 12h14" />
                </svg>
              </button>
            </>
          )}
          <span className="min-w-0 flex-1 truncate px-2 text-sm font-medium text-stone-600">
            {current?.title ?? ''}
          </span>
          {health === null && (
            <span className="rounded-full bg-red-50 px-2.5 py-1 text-xs text-red-800" data-testid="offline-badge">
              Backend offline
            </span>
          )}
          {health && !health.ready && (
            <span className="rounded-full bg-amber-50 px-2.5 py-1 text-xs text-amber-900" data-testid="notready-badge">
              Backend not ready
            </span>
          )}
        </header>
        {storageWarning && (
          <div role="status" className="mx-4 mb-1 rounded-lg bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
            Browser storage is full or unavailable: this conversation will not be kept after you close the page.
          </div>
        )}
        <div
          ref={scroller}
          className="min-h-0 flex-1 overflow-y-auto"
          role="log"
          aria-label="Conversation"
          aria-live="off"
        >
          {current ? (
            <div className="mx-auto w-full max-w-3xl space-y-6 px-3 pb-12 pt-6 sm:space-y-7 sm:px-4 sm:pt-8 xl:max-w-[52rem]">
              {current.messages.map((m, idx) => {
                const prevUser =
                  m.role === 'assistant'
                    ? current.messages
                        .slice(0, idx)
                        .reverse()
                        .find((x) => x.role === 'user')?.content ?? ''
                    : ''
                return (
                  <MessageView
                    key={m.id}
                    message={m}
                    developerMode={settings.developerMode}
                    questionText={prevUser}
                    onAskFollowUp={send}
                    onRetry={prevUser ? () => retryMessage(current.id, m.id, prevUser) : undefined}
                    disabled={pending}
                  />
                )
              })}
            </div>
          ) : (
            <Welcome onPick={send} disabled={false} health={health ?? null} />
          )}
        </div>
        <Composer disabled={pending} onSend={send} focusKey={currentId ?? 'new'} />
      </main>
      {aboutOpen && (
        <AboutPanel
          health={health ?? null}
          settings={settings}
          onSettings={setSettings}
          onClearAll={() => {
            setConversations([])
            setCurrentId(null)
            setAboutOpen(false)
          }}
          onClose={() => setAboutOpen(false)}
        />
      )}
    </div>
  )
}
