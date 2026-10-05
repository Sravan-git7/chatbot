import { useEffect, useState } from 'react'
import type { ApiStatus, ElaborationSectionKey, Message } from '../types'
import { answerForClipboard, copyText, getFollowUpQuestions } from '../util'
import DebugPanel from './DebugPanel'
import Markdown from './Markdown'
import { Sources, TopicReferenceCard, sourceDomId } from './Sources'

const STATUS_HEADLINE: Record<Exclude<ApiStatus, 'answered'>, string> = {
  documentation_unavailable: 'Documentation unavailable',
  unable_to_verify: 'Unable to verify',
  out_of_scope: 'Out of scope',
}

const ELABORATION_SECTION_HEADINGS: Record<ElaborationSectionKey, string> = {
  what_it_is_does: 'What it is / does',
  how_it_works_relationships: 'How it works / relationships',
  conditions_prerequisites: 'Important conditions or prerequisites',
  key_details: 'Key details',
}

function hasValidElaborationPresentation(sections: unknown, answer: string): boolean {
  if (!Array.isArray(sections) || sections.length === 0) return false

  const seenKeys = new Set<string>()
  const orderedLines: Array<{ order: number; line: string }> = []
  let hasOrders = false
  let missingOrders = false

  for (const rawSection of sections) {
    if (!rawSection || typeof rawSection !== 'object') return false
    const section = rawSection as Record<string, unknown>
    const key = section.key
    const lines = section.lines
    if (
      typeof key !== 'string' ||
      !Object.prototype.hasOwnProperty.call(ELABORATION_SECTION_HEADINGS, key) ||
      seenKeys.has(key) ||
      !Array.isArray(lines) ||
      lines.length === 0 ||
      !lines.every((line) => typeof line === 'string' && line.trim().length > 0)
    ) return false
    seenKeys.add(key)

    if (section.line_orders === undefined || section.line_orders === null) {
      missingOrders = true
      continue
    }
    hasOrders = true
    const orders = section.line_orders
    if (!Array.isArray(orders) || orders.length !== lines.length) return false
    for (let index = 0; index < orders.length; index += 1) {
      const order = orders[index]
      if (typeof order !== 'number' || !Number.isInteger(order) || order < 0) return false
      orderedLines.push({ order, line: lines[index] as string })
    }
  }

  if (hasOrders && missingOrders) return false
  if (!hasOrders) return sections.flatMap((section) => section.lines as string[]).join('\n') === answer

  orderedLines.sort((left, right) => left.order - right.order)
  if (orderedLines.some((entry, index) => entry.order !== index)) return false
  return orderedLines.map((entry) => entry.line).join('\n') === answer
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
      className="max-w-md rounded-2xl border border-stone-200 bg-white px-4 py-3 text-stone-600 shadow-2xs animate-answer-reveal"
      data-testid="loading"
    >
      <div className="flex items-center gap-3 text-sm">
        <span className="flex gap-1" aria-hidden="true">
          <span className="dot sura-dot" />
          <span className="dot sura-dot sura-dot-2" style={{ animationDelay: '.15s' }} />
          <span className="dot sura-dot sura-dot-3" style={{ animationDelay: '.3s' }} />
        </span>
        {/*
          The backend reports only one in-flight operation, so the headline states exactly that.
          The line below is a decorative UI hint of the work in progress - it never claims a step finished.
        */}
        <span className="font-medium text-stone-700">
          Searching the SAP Utilities documentation and preparing an answer
        </span>
      </div>
      <div className="mt-2.5 h-1 w-full rounded-full sura-shimmer-track" aria-hidden="true">
        <div className="sura-shimmer-bar rounded-full" />
      </div>
      <div className="mt-1.5 flex items-center gap-1.5 text-[11px] text-stone-400">
        <span
          key={stageIdx}
          data-testid="thinking-stage"
          className="animate-stage-fade"
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
      className="rounded-lg px-2 py-1 text-xs text-stone-500 transition hover:bg-stone-100 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
      aria-label="Copy answer"
    >
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy answer'}
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
}: {
  message: Message
  developerMode: boolean
  questionText?: string
  onAskFollowUp?: (q: string) => void
  onRetry?: () => void
  disabled?: boolean
}) {
  const [highlight, setHighlight] = useState<string | null>(null)
  if (message.role === 'user') {
    return (
      <div className="flex justify-end animate-answer-reveal" data-testid="user-message">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-stone-200/70 px-4 py-2.5 text-answer text-stone-900 lg:max-w-[75%] xl:text-base">
          {message.content}
        </div>
      </div>
    )
  }

  const r = message.result
  const cite = (marker: string) => {
    setHighlight(marker)
    const el = document.getElementById(sourceDomId(message.id, marker))
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    const card = el?.closest('li') as HTMLElement | null
    card?.focus?.({ preventScroll: true })
    setTimeout(() => setHighlight((h) => (h === marker ? null : h)), 1800)
  }

  const followUps =
    r && r.status === 'answered' ? getFollowUpQuestions(questionText ?? '', r) : []
  const elaborationSections = r?.metadata.elaboration_sections
  const showElaborationSections = Boolean(
    r?.status === 'answered' && hasValidElaborationPresentation(elaborationSections, r.answer),
  )

  return (
    <div className="flex gap-3 sm:gap-4 lg:gap-5" data-testid="assistant-message">
      <div
        className="mt-1 hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-[11px] font-bold text-white sm:flex"
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
            className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900 animate-answer-reveal"
            data-testid="error-message"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <div className="font-medium">
                  {message.error.kind === 'offline'
                    ? 'Service unreachable'
                    : message.error.kind === 'timeout'
                      ? 'Request timed out'
                      : message.error.kind === 'malformed'
                        ? 'Unexpected response'
                        : 'The request failed'}
                </div>
                <div className="mt-0.5">{message.error.message}</div>
              </div>
              {onRetry && (
                <button
                  type="button"
                  data-testid="retry-button"
                  disabled={disabled}
                  onClick={onRetry}
                  className="shrink-0 rounded-lg border border-red-300 bg-white px-2.5 py-1 text-xs font-medium text-red-900 transition hover:bg-red-100/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-700 disabled:opacity-50 cursor-pointer"
                >
                  Retry
                </button>
              )}
            </div>
          </div>
        )}

        {r && r.status === 'answered' && (
          <div className="animate-answer-reveal">
            {showElaborationSections && elaborationSections ? (
              <div className="space-y-4" data-testid="elaboration-sections">
                {elaborationSections.map((section, index) => (
                  <section key={`${section.key}-${index}`} className="space-y-1.5">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-stone-500">
                      {ELABORATION_SECTION_HEADINGS[section.key]}
                    </h3>
                    <Markdown
                      text={section.lines.join('\n')}
                      markers={new Set(r.sources.map((s) => s.marker).filter((m): m is string => !!m))}
                      onCite={cite}
                    />
                  </section>
                ))}
              </div>
            ) : (
              <Markdown
                text={r.answer}
                markers={new Set(r.sources.map((s) => s.marker).filter((m): m is string => !!m))}
                onCite={cite}
              />
            )}
            <Sources messageId={message.id} sources={r.sources} highlight={highlight} />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <CopyButton text={answerForClipboard(r.answer, r.sources)} />
              {r.metadata.grounded && (
                <span
                  className="inline-flex items-center gap-1 text-xs text-stone-400"
                  title="Every sentence was checked against the cited documentation text"
                >
                  <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
                  Checked against the documentation
                </span>
              )}
            </div>

            {followUps.length > 0 && onAskFollowUp && (
              <div
                data-testid="follow-up-questions"
                aria-label="You might also want to know"
                className="mt-5 rounded-xl border border-stone-200/80 bg-white/80 p-3.5 sura-followups-reveal"
              >
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                  You might also want to know
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {followUps.map((q) => (
                    <button
                      key={q}
                      type="button"
                      disabled={disabled}
                      onClick={() => onAskFollowUp(q)}
                      className="rounded-lg border border-stone-200 bg-stone-50 px-2.5 py-1.5 text-left text-xs text-stone-700 transition enabled:hover:border-accent enabled:hover:bg-accent-soft/40 enabled:hover:text-stone-900 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {r && r.status !== 'answered' && (
          <div
            className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-answer text-stone-800 xl:text-base animate-answer-reveal"
            data-testid="status-note"
            data-status={r.status}
          >
            <div className="text-xs font-semibold uppercase tracking-wider text-amber-800">
              {STATUS_HEADLINE[r.status]}
            </div>
            <p className="mt-1 leading-relaxed">{r.answer}</p>
            {r.topic_reference && <TopicReferenceCard reference={r.topic_reference} />}
          </div>
        )}

        {r && developerMode && r.debug && <DebugPanel result={r} />}
      </div>
    </div>
  )
}
