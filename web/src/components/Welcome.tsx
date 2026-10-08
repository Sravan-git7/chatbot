import { useState } from 'react'
import type { Health } from '../types'
import { EXPLORE_TOPICS } from '../util'

export const EXAMPLE_PROMPTS = [
  'How does billing work?',
  'What is a contract account?',
  'What is the invoicing process?',
  'How does a contract account relate to a business partner?',
  'How do I create an installment plan?',
  'How are devices managed?',
]

export default function Welcome({
  onPick,
  disabled,
  health,
}: {
  onPick: (q: string) => void
  disabled: boolean
  health: Health | null | undefined
}) {
  const [activeTopicId, setActiveTopicId] = useState<string>(EXPLORE_TOPICS[0].id)
  const activeTopic = EXPLORE_TOPICS.find((t) => t.id === activeTopicId) ?? EXPLORE_TOPICS[0]

  return (
    <div
      data-testid="welcome-screen"
      className="mx-auto flex min-h-full w-full max-w-3xl flex-col items-center justify-center px-4 py-8 text-center sm:py-10 xl:max-w-[54rem] animate-answer-reveal"
    >
      {/* Brand Hero Icon */}
      <div
        className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent text-base font-bold text-white shadow-md shadow-accent/15"
        aria-hidden="true"
      >
        SU
      </div>

      {/* SURA Assistant Status Pill */}
      <div
        data-testid="sura-intro"
        className="mb-3 inline-flex items-center gap-2 rounded-full border border-stone-200/90 bg-white px-3.5 py-1 text-xs font-medium text-stone-700 shadow-2xs"
      >
        <span className="h-2 w-2 rounded-full bg-accent animate-pulse" aria-hidden="true" />
        <span>Documentation-grounded assistant</span>
      </div>

      {/* Main Heading */}
      <h1 className="text-balance text-3xl font-semibold tracking-tight text-stone-900 sm:text-4xl md:text-[2.65rem] md:leading-[1.18]">
        Ask about SAP Utilities documentation.
      </h1>

      {/* Supporting Text */}
      <p className="mt-3 max-w-xl text-answer leading-relaxed text-stone-600 sm:text-base">
        Find grounded answers about billing, invoicing, contract accounts, business partners, and other subjects
        covered by the available SAP Utilities documentation.
      </p>
      {/* Coverage Status */}
      {health?.ready && health.pages_available != null && health.topics != null && (
        <div
          className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-stone-100/90 px-2.5 py-1 text-[11px] font-medium text-stone-700"
          data-testid="coverage"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className="text-accent" aria-hidden="true"><path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1-2.5-2.5Z"/><path d="M6 6h10M6 10h10"/></svg>
          Currently {health.pages_available} of {health.topics} documentation sources are available.
        </div>
      )}
      {health === undefined && (
        <p className="mt-3 text-xs text-stone-500" role="status" data-testid="health-checking">
          Checking service availability…
        </p>
      )}
      {health === null && (
        <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-1 text-xs text-red-700" role="alert" data-testid="offline-note">
          The RAG service is not reachable. Start the backend, then reload.
        </p>
      )}
      {health && !health.ready && (
        <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1 text-xs text-amber-900" role="status" data-testid="notready-note">
          The RAG service is not ready, so answers may be unavailable.
          {health.reason ? ` ${health.reason}` : ''}
        </p>
      )}

      {/* Suggested Questions (Max 6) */}
      <section className="mt-6 w-full max-w-2xl text-left" aria-labelledby="suggested-questions-heading">
        <div className="mb-2.5 flex items-center justify-between px-1">
          <h2 id="suggested-questions-heading" className="text-[11px] font-semibold uppercase tracking-wider text-stone-700">
            Suggested questions
          </h2>
          <span className="text-[11px] text-stone-600">Click to ask</span>
        </div>
        <div className="grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
          {EXAMPLE_PROMPTS.map((p) => (
            <button
              key={p}
              type="button"
              disabled={disabled}
              onClick={() => onPick(p)}
              className="group flex items-center justify-between rounded-xl border border-stone-200/90 bg-white p-3.5 text-left text-xs font-medium leading-snug text-stone-800 shadow-2xs transition-all enabled:hover:border-accent/60 enabled:hover:bg-accent-soft/40 enabled:hover:shadow-xs disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
            >
              <span className="pr-2">{p}</span>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="shrink-0 text-stone-400 transition-transform group-hover:translate-x-0.5 group-hover:text-accent"
                aria-hidden="true"
              >
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
      </section>

      {/* Explore SAP Utilities - Knowledge Discovery */}
      <section
        data-testid="explore-topics"
        aria-label="Explore SAP Utilities"
        className="mt-6 w-full max-w-2xl rounded-2xl border border-stone-200/90 bg-white p-4 text-left shadow-2xs sm:p-5"
      >
        <div className="mb-3 flex flex-wrap items-center justify-between gap-1">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-stone-700">
            Explore SAP Utilities
          </h2>
          <span className="text-[11px] text-stone-600">Browse by topic area</span>
        </div>

        {/* Polished Segmented Control */}
        <div
          role="tablist"
          aria-label="SAP Utilities topic categories"
          className="mb-3.5 flex flex-wrap gap-1 rounded-xl bg-stone-100 p-1 border border-stone-200/60"
        >
          {EXPLORE_TOPICS.map((topic) => {
            const isSelected = topic.id === activeTopic.id
            return (
              <button
                key={topic.id}
                type="button"
                role="tab"
                id={`topic-tab-${topic.id}`}
                aria-controls="topic-panel"
                aria-selected={isSelected}
                tabIndex={isSelected ? 0 : -1}
                data-testid={`topic-tab-${topic.id}`}
                onClick={() => setActiveTopicId(topic.id)}
                onKeyDown={(event) => {
                  const currentIndex = EXPLORE_TOPICS.findIndex((item) => item.id === topic.id)
                  let nextIndex: number | null = null
                  if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % EXPLORE_TOPICS.length
                  if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + EXPLORE_TOPICS.length) % EXPLORE_TOPICS.length
                  if (event.key === 'Home') nextIndex = 0
                  if (event.key === 'End') nextIndex = EXPLORE_TOPICS.length - 1
                  if (nextIndex !== null) {
                    event.preventDefault()
                    const nextTopic = EXPLORE_TOPICS[nextIndex]
                    setActiveTopicId(nextTopic.id)
                    document.getElementById(`topic-tab-${nextTopic.id}`)?.focus()
                  }
                }}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
                  isSelected
                    ? 'bg-white text-stone-900 shadow-2xs font-semibold'
                    : 'text-stone-600 hover:text-stone-900 hover:bg-stone-200/60'
                }`}
              >
                {topic.label}
              </button>
            )
          })}
        </div>

        {/* Topic Content Panel */}
        <div
          role="tabpanel"
          id="topic-panel"
          aria-labelledby={`topic-tab-${activeTopic.id}`}
          tabIndex={0}
          data-testid="topic-panel"
          className="rounded-xl border border-stone-200/70 bg-[#faf9f6] p-3.5"
        >
          <p className="mb-2.5 text-xs text-stone-600">{activeTopic.description}</p>
          <div className="flex flex-wrap gap-1.5">
            {activeTopic.questions.map((q) => (
              <button
                key={`${activeTopic.id}-${q}`}
                type="button"
                disabled={disabled}
                onClick={() => onPick(q)}
                className="rounded-lg border border-stone-200/90 bg-white px-3 py-1.5 text-left text-xs font-medium text-stone-700 shadow-2xs transition enabled:hover:border-accent enabled:hover:bg-accent-soft/50 enabled:hover:text-accent-dark disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      </section>
    </div>
  )
}
