import { useEffect, useState } from 'react'
import type { ApiStatus, Message, Source } from '../types'
import { answerForClipboard, copyText, getFollowUpQuestions, isHttpUrl } from '../util'
import DebugPanel from './DebugPanel'
import { Sources, TopicReferenceCard, sourceDomId } from './Sources'
import StructuredAnswer, { buildMarkerMap, visibleAnswerText } from './StructuredAnswer'

const STATUS_HEADLINE: Record<Exclude<ApiStatus, 'answered'>, string> = {
  documentation_unavailable: 'Documentation unavailable',
  unable_to_verify: 'Unable to verify',
  out_of_scope: 'Out of scope',
  no_additional_verified_evidence: 'No more verified detail',
}

const STATUS_TONE: Record<Exclude<ApiStatus, 'answered'>, { card: string; badge: string; dot: string }> = {
  documentation_unavailable: {
    card: 'border-amber-200 bg-amber-50/70',
    badge: 'bg-amber-100 text-amber-900',
    dot: 'bg-amber-600',
  },
  unable_to_verify: {
    card: 'border-rose-200 bg-rose-50/70',
    badge: 'bg-rose-100 text-rose-900',
    dot: 'bg-rose-600',
  },
  out_of_scope: {
    card: 'border-stone-200/90 bg-[#faf9f6]',
    badge: 'bg-stone-200/70 text-stone-700',
    dot: 'bg-stone-500',
  },
  no_additional_verified_evidence: {
    card: 'border-accent-border bg-accent-soft',
    badge: 'bg-white/80 text-accent-dark',
    dot: 'bg-accent',
  },
}

export const THINKING_STAGES = [
  'Searching SAP documentation...',
  'Finding relevant evidence...',
  'Verifying sources...',
  'Preparing answer...',
]

export function Thinking() {
  const [stageIdx, setStageIdx] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setStageIdx((prev) => (prev < THINKING_STAGES.length - 1 ? prev + 1 : prev))
    }, 240)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div
      role="status"
      aria-live="polite"
      className="max-w-md rounded-2xl border border-stone-200/90 bg-white p-4 text-stone-600 shadow-2xs animate-answer-reveal"
      data-testid="loading"
    >
      <div className="flex items-center gap-2.5 text-xs">
        <span className="flex gap-1" aria-hidden="true">
          <span className="dot sura-dot" />
          <span className="dot sura-dot sura-dot-2" style={{ animationDelay: '.15s' }} />
          <span className="dot sura-dot sura-dot-3" style={{ animationDelay: '.3s' }} />
        </span>
        <span className="font-medium text-stone-800">
          Searching the SAP Utilities documentation and preparing an answer
        </span>
      </div>
      <div className="mt-3 h-1 w-full rounded-full sura-shimmer-track" aria-hidden="true">
        <div className="sura-shimmer-bar rounded-full" />
      </div>
      <div className="mt-2 flex items-center gap-1.5 text-[11px] text-stone-400">
        <span
          key={stageIdx}
          data-testid="thinking-stage"
          className="animate-stage-fade font-medium text-stone-500"
          aria-hidden="true"
        >
          {THINKING_STAGES[stageIdx]}
        </span>
      </div>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  return (
    <button
      type="button"
      onClick={async () => {
        setState((await copyText(text)) ? 'copied' : 'failed')
        setTimeout(() => setState('idle'), 1500)
      }}
      className="inline-flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-600 shadow-2xs transition hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
      aria-label="Copy answer"
    >
      <svg
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-stone-400"
        aria-hidden="true"
      >
        <rect width="14" height="14" x="8" y="8" rx="2" ry="2" />
        <path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2" />
      </svg>
      <span aria-live="polite" aria-atomic="true">{state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy answer'}</span>
    </button>
  )
}

export default function MessageView({
  message,
  developerMode,
  questionText,
  onAskFollowUp,
  onRetry,
  disabled,
  showElaborate = true,
  showRelatedQuestions = true,
  exhaustedSource = null,
}: {
  message: Message
  developerMode: boolean
  questionText?: string
  onAskFollowUp?: (q: string) => void
  onRetry?: () => void
  disabled?: boolean
  showElaborate?: boolean
  showRelatedQuestions?: boolean
  exhaustedSource?: Source | null
}) {
  const [highlight, setHighlight] = useState<string | null>(null)
  if (message.role === 'user') {
    return (
      <div className="flex justify-end animate-answer-reveal" data-testid="user-message">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl border border-stone-200/60 bg-stone-100 px-4 py-2.5 text-answer text-stone-900 shadow-2xs lg:max-w-[75%] xl:text-base">
          {message.content}
        </div>
      </div>
    )
  }

  const r = message.result
  const followUpCategory = r?.metadata.follow_up_category
  const isElaboration = r?.status === 'answered'
    && (followUpCategory === 'elaborate' || (followUpCategory == null && questionText?.trim().toLowerCase() === 'elaborate'))
  const exhaustedTopicId = r?.metadata.topic_identity?.source_id ?? r?.metadata.card_id ?? null
  const exhaustedOpenSource = r?.status === 'no_additional_verified_evidence'
    ? r.sources.find((source) => !!exhaustedTopicId && source.source_id === exhaustedTopicId && isHttpUrl(source.url))
      ?? (exhaustedTopicId && exhaustedSource?.source_id === exhaustedTopicId && isHttpUrl(exhaustedSource.url) ? exhaustedSource : null)
    : null
  const cite = (marker: string) => {
    setHighlight(marker)
    const el = document.getElementById(sourceDomId(message.id, marker))
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    const card = el?.closest('li') as HTMLElement | null
    card?.focus?.({ preventScroll: true })
    setTimeout(() => setHighlight((h) => (h === marker ? null : h)), 1800)
  }

  const followUps =
    showRelatedQuestions && r?.status === 'answered'
      ? getFollowUpQuestions(questionText ?? '', r)
      : []

  return (
    <div className="flex gap-3 sm:gap-4 lg:gap-5" data-testid="assistant-message">
      {/* SURA Brand Avatar */}
      <div
        className="mt-1 hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-[11px] font-bold text-white shadow-2xs sm:flex"
        aria-hidden="true"
        title="SURA"
      >
        SU
      </div>
      <div className="min-w-0 flex-1">
        {message.pending && <Thinking />}

        {message.error && (
          <div
            role="alert"
            className="rounded-xl border border-red-200 bg-red-50 p-4 text-xs text-red-900 animate-answer-reveal shadow-2xs"
            data-testid="error-message"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="font-semibold text-red-950">
                  {message.error.kind === 'offline'
                    ? 'Service unreachable'
                    : message.error.kind === 'timeout'
                      ? 'Request timed out'
                      : message.error.kind === 'malformed'
                        ? 'Unexpected response'
                        : 'The request failed'}
                </div>
                <div className="mt-1 leading-relaxed text-red-800">{message.error.message}</div>
              </div>
              {onRetry && (
                <button
                  type="button"
                  data-testid="retry-button"
                  disabled={disabled}
                  onClick={onRetry}
                  className="shrink-0 rounded-lg border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-900 shadow-2xs transition hover:bg-red-100/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-700 disabled:opacity-50 cursor-pointer"
                >
                  Retry
                </button>
              )}
            </div>
          </div>
        )}

        {r && r.status === 'answered' && (() => {
          const visibleText = visibleAnswerText(r.structured_answer, r.answer)
          const markerMap = buildMarkerMap(visibleText, r.sources)
          return (
            <div className="animate-answer-reveal">
              <h2 className="sr-only">Answer</h2>
              <StructuredAnswer
                structuredAnswer={r.structured_answer}
                fallbackAnswer={r.answer}
                sources={r.sources}
                markerMap={markerMap}
                onCite={cite}
                isElaboration={isElaboration}
              />
              <Sources messageId={message.id} sources={r.sources} markerMap={markerMap} highlight={highlight} />

              {/* Answer Footer Actions & Verification */}
              <div className="mt-4 flex flex-wrap items-center gap-3 pt-1">
                <CopyButton text={answerForClipboard(visibleText, r.sources, markerMap)} />
                {onAskFollowUp && showElaborate && r.metadata.can_elaborate === true && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => onAskFollowUp('elaborate')}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-600 shadow-2xs transition hover:border-stone-300 hover:bg-stone-50 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-50 cursor-pointer"
                    aria-label="Elaborate"
                    data-testid="elaborate-button"
                  >
                    <svg
                      width="13"
                      height="13"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="text-stone-400"
                      aria-hidden="true"
                    >
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                    Elaborate
                  </button>
                )}
                {r.metadata.grounded && (
                  <span
                    className="inline-flex items-center gap-1.5 text-xs text-stone-500"
                    title="Every sentence was checked against the cited documentation text"
                  >
                    <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
                    Checked against the documentation
                  </span>
                )}
              </div>

              {/* Suggested Follow-ups */}
              {followUps.length > 0 && onAskFollowUp && (
                <section
                  data-testid="follow-up-questions"
                  aria-label="You might also want to know"
                  className="mt-6 rounded-xl border border-stone-200/80 bg-white/70 p-4 shadow-2xs sura-followups-reveal"
                >
                  <h3 className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                    You might also want to know
                  </h3>
                  <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                    {followUps.map((q) => (
                      <li key={q} className="min-w-0">
                        <button
                          type="button"
                          disabled={disabled}
                          onClick={() => onAskFollowUp(q)}
                          className="flex w-full min-w-0 items-start rounded-lg border border-stone-200/90 bg-white px-3 py-2 text-left text-xs font-medium text-stone-700 shadow-2xs transition enabled:hover:border-accent enabled:hover:bg-accent-soft/40 enabled:hover:text-stone-900 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer whitespace-normal break-words [overflow-wrap:anywhere]"
                        >
                          {q}
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          )
        })()}

        {/* Status states use distinct tones so exhausted evidence is not mistaken for an abstention or missing page. */}
        {r && r.status !== 'answered' && (() => {
          const tone = STATUS_TONE[r.status]
          return (
          <div
            role="status"
            aria-live="polite"
            className={`rounded-xl border p-4 text-answer text-stone-800 shadow-2xs xl:text-base animate-answer-reveal ${tone.card}`}
            data-testid="status-note"
            data-status={r.status}
          >
            <div className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${tone.badge}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} aria-hidden="true" />
              {STATUS_HEADLINE[r.status]}
            </div>
            <p className="mt-2.5 leading-relaxed text-stone-800">{r.answer}</p>
            {r.status === 'out_of_scope' && (
              <div className="mt-2 text-xs text-stone-500">
                <p>
                  SURA answers questions about topics covered by the available SAP Utilities documentation, such as billing, invoicing, contract accounts, and incoming payments.
                </p>
                {onAskFollowUp && (
                  <div className="mt-2.5 flex flex-wrap gap-2">
                    {['How does billing work?', 'What is a contract account?'].map((ex) => (
                      <button
                        key={ex}
                        type="button"
                        disabled={disabled}
                        onClick={() => onAskFollowUp(ex)}
                        className="inline-flex items-center rounded-lg border border-stone-200 bg-white px-2.5 py-1 text-xs font-medium text-stone-700 shadow-2xs hover:border-accent hover:text-stone-900 cursor-pointer transition"
                      >
                        {ex}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            {r.status === 'unable_to_verify' && r.metadata?.pipeline_status !== 'unresolved_identity' && (
              <p className="mt-1.5 text-xs text-stone-500">
                Try including the SAP Utilities topic or component you're asking about.
              </p>
            )}
            {r.status === 'no_additional_verified_evidence' && (
              <>
                <p className="mt-1.5 text-xs text-stone-600">
                  Ask a new question about this topic, or switch to another SAP Utilities topic.
                </p>
                {exhaustedOpenSource && isHttpUrl(exhaustedOpenSource.url) && (
                  <div className="mt-3 flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs" data-testid="exhausted-source">
                    <a
                      href={exhaustedOpenSource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`Open source: ${exhaustedOpenSource.title || 'SAP Help page'}`}
                      className="inline-flex shrink-0 items-center gap-1 font-medium text-accent underline-offset-2 hover:underline focus-visible:rounded-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                    >
                      Open source <span aria-hidden="true">↗</span>
                    </a>
                    {exhaustedOpenSource.title && (
                      <span className="min-w-0 break-words text-stone-600 [overflow-wrap:anywhere]">{exhaustedOpenSource.title}</span>
                    )}
                  </div>
                )}
              </>
            )}
            {r.topic_reference && <TopicReferenceCard reference={r.topic_reference} pageAvailable={r.metadata?.page_available} />}
          </div>
          )
        })()}

        {r && developerMode && r.debug && <DebugPanel result={r} />}
      </div>
    </div>
  )
}
