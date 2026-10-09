import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, fetchHealth, sendChat } from './api'
import AboutPanel from './components/AboutPanel'
import Composer from './components/Composer'
import MessageView from './components/MessageView'
import Sidebar from './components/Sidebar'
import Welcome from './components/Welcome'
import { loadConversations, loadSettings, newId, saveConversations, saveSettings, titleFrom } from './storage'
import { turnContext } from './followup'
import type { ChatError, Conversation, Health, Message, Settings, Source } from './types'
import { isHttpUrl } from './util'

const DESKTOP_QUERY = '(min-width: 768px)'
const MIN_THINKING_MS = import.meta.env.MODE === 'test' ? 0 : 840

function isElaborationMessage(messages: Message[], index: number, message: Message): boolean {
  const category = message.result?.metadata.follow_up_category
  if (category != null) return category === 'elaborate'
  const previousUser = messages.slice(0, index).reverse().find((item) => item.role === 'user')
  return previousUser?.content.trim().toLowerCase() === 'elaborate'
}

function latestGroundedBaseAnswer(messages: Message[]): Message | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index]
    const result = message.result
    if (
      message.role === 'assistant'
      && result?.status === 'answered'
      && result.metadata.grounded === true
      && !isElaborationMessage(messages, index, message)
    ) return message
  }
  return null
}

function sourceForExhaustedResponse(messages: Message[], messageIndex: number, message: Message): Source | null {
  const result = message.result
  if (result?.status !== 'no_additional_verified_evidence') return null
  const topicId = result.metadata.topic_identity?.source_id ?? result.metadata.card_id
  if (!topicId) return null

  const responseSource = result.sources.find((source) => source.source_id === topicId && isHttpUrl(source.url))
  if (responseSource) return responseSource

  // The exhausted response may carry no citations. Reuse only a URL actually cited by an earlier grounded answer
  // for the exact same backend topic identity; never borrow a source from a different topic/conversation.
  for (let index = messageIndex - 1; index >= 0; index -= 1) {
    const earlier = messages[index]
    const earlierResult = earlier.result
    if (earlier.role !== 'assistant' || earlierResult?.status !== 'answered' || earlierResult.metadata.grounded !== true) continue
    const earlierTopicId = earlierResult.metadata.topic_identity?.source_id ?? earlierResult.metadata.card_id
    if (earlierTopicId !== topicId) continue
    const source = earlierResult.sources.find((candidate) => candidate.source_id === topicId && isHttpUrl(candidate.url))
    if (source) return source
  }
  return null
}

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
  const activeGroundedAnswer = current ? latestGroundedBaseAnswer(current.messages) : null
  const relatedAnswerId = activeGroundedAnswer?.id ?? null
  const activeTopicId = activeGroundedAnswer?.result?.metadata.topic_identity?.source_id
    ?? activeGroundedAnswer?.result?.metadata.card_id
    ?? null

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

  const disableElaborationForTopic = useCallback((convId: string, sourceId: string | null) => {
    if (!sourceId) return
    // The backend has authoritatively exhausted this topic's verified evidence. Apply that can_elaborate=false
    // decision to its earlier grounded answer cards as well, so scrolling up cannot expose a stale action. This is
    // a presentation update only; it does not infer evidence availability or alter any answer/citation.
    setConversations((list) => list.map((conversation) => conversation.id !== convId ? conversation : ({
      ...conversation,
      messages: conversation.messages.map((message) => {
        const result = message.result
        const messageTopic = result?.metadata.topic_identity?.source_id ?? result?.metadata.card_id
        if (message.role !== 'assistant' || result?.status !== 'answered' || messageTopic !== sourceId) return message
        return {
          ...message,
          result: { ...result, metadata: { ...result.metadata, can_elaborate: false } },
        }
      }),
    })))
  }, [])

  const send = useCallback(
    async (text: string) => {
      const now = Date.now()
      const convId = currentId ?? newId()
      const user: Message = { id: newId(), role: 'user', content: text, createdAt: now }
      const reply: Message = { id: newId(), role: 'assistant', content: '', createdAt: now, pending: true }
      const context = turnContext(conversations.find((conversation) => conversation.id === convId) ?? null) ?? { questions: [] }
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
        const result = await sendChat(text, convId, settingsRef.current.developerMode, { context })
        const elapsed = Date.now() - startedAt
        if (MIN_THINKING_MS > 0 && elapsed < MIN_THINKING_MS) {
          await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed))
        }
        if (result.status === 'no_additional_verified_evidence' && result.metadata.can_elaborate === false) {
          disableElaborationForTopic(convId, result.metadata.topic_identity?.source_id ?? result.metadata.card_id)
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
    [currentId, patchMessage, disableElaborationForTopic, conversations, pending],
  )

  const retryMessage = useCallback(
    async (convId: string, replyId: string, userMessageId: string, questionText: string) => {
      if (!questionText.trim() || pending) return
      const conversation = conversations.find((item) => item.id === convId) ?? null
      const context = turnContext(conversation, userMessageId) ?? { questions: [] }
      patchMessage(convId, replyId, { pending: true, error: undefined })
      const startedAt = Date.now()
      try {
        const result = await sendChat(questionText, convId, settingsRef.current.developerMode, { context })
        const elapsed = Date.now() - startedAt
        if (MIN_THINKING_MS > 0 && elapsed < MIN_THINKING_MS) {
          await new Promise((r) => setTimeout(r, MIN_THINKING_MS - elapsed))
        }
        if (result.status === 'no_additional_verified_evidence' && result.metadata.can_elaborate === false) {
          disableElaborationForTopic(convId, result.metadata.topic_identity?.source_id ?? result.metadata.card_id)
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
    [pending, patchMessage, disableElaborationForTopic, conversations],
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
      <main className="flex min-w-0 flex-1 flex-col bg-surface">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-stone-200/60 bg-surface/80 px-2 sm:px-3.5 backdrop-blur-xs">
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            {!sidebarOpen && (
              <>
                <button
                  type="button"
                  onClick={() => setSidebarOpen(true)}
                  aria-label="Open sidebar"
                  aria-controls="sidebar"
                  aria-expanded={false}
                  className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-200/60 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer transition"
                >
                  <svg
                    width="18"
                    height="18"
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
                  className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-200/60 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer transition"
                >
                  <svg
                    width="18"
                    height="18"
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
            <h1 className="min-w-0 flex-1 truncate px-2 text-xs font-semibold text-stone-800">
              {current?.title || 'SURA — SAP Utilities Documentation Assistant'}
            </h1>
          </div>

          <div className="flex items-center gap-2">
            {health === null && (
              <span className="rounded-full border border-red-200 bg-red-50 px-2.5 py-0.5 text-[11px] font-medium text-red-700" data-testid="offline-badge">
                Backend offline
              </span>
            )}
            {health && !health.ready && (
              <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-0.5 text-[11px] font-medium text-amber-800" data-testid="notready-badge">
                Backend not ready
              </span>
            )}
          </div>
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
                const prevUserMessage =
                  m.role === 'assistant'
                    ? current.messages
                        .slice(0, idx)
                        .reverse()
                        .find((x) => x.role === 'user') ?? null
                    : null
                const prevUser = prevUserMessage?.content ?? ''
                const messageTopicId = m.result?.metadata.topic_identity?.source_id ?? m.result?.metadata.card_id ?? null
                const showElaborate = activeTopicId ? messageTopicId === activeTopicId : m.id === activeGroundedAnswer?.id
                return (
                  <MessageView
                    key={m.id}
                    message={m}
                    developerMode={settings.developerMode}
                    questionText={prevUser}
                    showElaborate={showElaborate}
                    showRelatedQuestions={m.id === relatedAnswerId}
                    exhaustedSource={sourceForExhaustedResponse(current.messages, idx, m)}
                    onAskFollowUp={send}
                    onRetry={prevUserMessage ? () => retryMessage(current.id, m.id, prevUserMessage.id, prevUser) : undefined}
                    disabled={pending}
                  />
                )
              })}
            </div>
          ) : (
            <Welcome onPick={send} disabled={false} health={health} />
          )}
        </div>
        <Composer disabled={pending} onSend={send} focusKey={currentId ?? 'new'} />
      </main>
      {aboutOpen && (
        <AboutPanel
          health={health}
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
