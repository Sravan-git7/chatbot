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
  health: Health | null
}) {
  const [activeTopicId, setActiveTopicId] = useState<string>(EXPLORE_TOPICS[0].id)
  const activeTopic = EXPLORE_TOPICS.find((t) => t.id === activeTopicId) ?? EXPLORE_TOPICS[0]

  return (
    <div
      data-testid="welcome-screen"
      className="mx-auto flex min-h-full w-full max-w-3xl flex-col items-center justify-center px-4 py-10 text-center sm:py-14 xl:max-w-[52rem] animate-answer-reveal"
    >
      <div
        className="mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-sm font-bold text-white shadow-xs"
        aria-hidden="true"
      >
        SU
      </div>

      {/* SURA Assistant Introduction */}
      <div
        data-testid="sura-intro"
        className="mb-4 inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white px-3.5 py-1 text-xs font-medium text-stone-700 shadow-2xs"
      >
        <span className="h-2 w-2 rounded-full bg-accent" aria-hidden="true" />
        <span>Hi, I'm SURA — your SAP Utilities documentation assistant</span>
      </div>

      <h1 className="text-balance text-3xl font-semibold tracking-tight text-stone-900 sm:text-4xl">
        Ask SAP Utilities anything.
      </h1>

      <p className="mt-2.5 max-w-xl text-answer text-stone-600">
        Hi, I'm SURA. I'm your SAP Utilities documentation assistant. Ask me about billing, invoicing,
        contract accounts, business partners, and other topics covered by the documentation.
      </p>
      <p className="mt-1 text-xs text-stone-500">
        Answers are generated from the available SAP Utilities documentation.
      </p>

      {health?.ready && health.pages_available != null && health.topics != null && (
        <p className="mt-1.5 text-xs text-stone-500" data-testid="coverage">
          Currently {health.pages_available} of {health.topics} documentation pages are available.
        </p>
      )}
      {health === null && (
        <p className="mt-2 text-xs text-red-700" role="alert" data-testid="offline-note">
          The RAG service is not reachable. Start the backend, then reload.
        </p>
      )}

      {/* Suggested Questions */}
      <div className="mt-7 w-full max-w-2xl text-left">
        <div className="mb-2 flex items-center justify-between px-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-stone-500">
            Suggested questions
          </span>
          <span className="text-[11px] text-stone-400">Click to ask</span>
        </div>
        <div className="grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
          {EXAMPLE_PROMPTS.map((p) => (
            <button
              key={p}
              type="button"
              disabled={disabled}
              onClick={() => onPick(p)}
              className="rounded-2xl border border-stone-200 bg-white px-4 py-3.5 text-left text-ui leading-snug text-stone-800 shadow-2xs transition enabled:hover:border-accent enabled:hover:bg-accent-soft/35 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Explore SAP Utilities - Knowledge Discovery */}
      <section
        data-testid="explore-topics"
        aria-label="Explore SAP Utilities"
        className="mt-7 w-full max-w-2xl rounded-2xl border border-stone-200 bg-white p-4 text-left shadow-2xs sm:p-5"
      >
        <div className="mb-2.5 flex flex-wrap items-center justify-between gap-1">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
            Explore SAP Utilities
          </h2>
          <span className="text-[11px] text-stone-400">Browse by topic area</span>
        </div>

        <div
          role="tablist"
          aria-label="SAP Utilities topic categories"
          className="mb-3 flex flex-wrap gap-1.5"
        >
          {EXPLORE_TOPICS.map((topic) => {
            const isSelected = topic.id === activeTopic.id
            return (
              <button
                key={topic.id}
                type="button"
                role="tab"
                aria-selected={isSelected}
                data-testid={`topic-tab-${topic.id}`}
                onClick={() => setActiveTopicId(topic.id)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
                  isSelected
                    ? 'bg-accent text-white shadow-2xs'
                    : 'bg-stone-100 text-stone-700 hover:bg-stone-200/80 hover:text-stone-900'
                }`}
              >
                {topic.label}
              </button>
            )
          })}
        </div>

        <div
          role="tabpanel"
          data-testid="topic-panel"
          className="rounded-xl border border-stone-200/70 bg-stone-50/80 p-3"
        >
          <p className="mb-2 text-xs text-stone-600">{activeTopic.description}</p>
          <div className="flex flex-wrap gap-1.5">
            {activeTopic.questions.map((q) => (
              <button
                key={`${activeTopic.id}-${q}`}
                type="button"
                disabled={disabled}
                onClick={() => onPick(q)}
                className="rounded-lg border border-stone-200 bg-white px-3 py-1.5 text-left text-xs text-stone-800 transition enabled:hover:border-accent enabled:hover:bg-accent-soft/40 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
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
