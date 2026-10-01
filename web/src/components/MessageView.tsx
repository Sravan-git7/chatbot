import { useState } from 'react'
import type { ApiStatus, Message } from '../types'
import { answerForClipboard, copyText } from '../util'
import DebugPanel from './DebugPanel'
import Markdown from './Markdown'
import { Sources, TopicReferenceCard, sourceDomId } from './Sources'

const STATUS_HEADLINE: Record<Exclude<ApiStatus, 'answered'>, string> = {
  documentation_unavailable: 'Documentation unavailable',
  unable_to_verify: 'Unable to verify',
  out_of_scope: 'Out of scope',
}

export function Thinking() {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-3 text-stone-500" data-testid="loading">
      <span className="flex gap-1" aria-hidden="true">
        <span className="dot" /><span className="dot" style={{ animationDelay: '.15s' }} /><span className="dot" style={{ animationDelay: '.3s' }} />
      </span>
      <span>Searching the SAP Utilities documentation and preparing an answer…</span>
    </div>
  )
}

function CopyButton({ text }: { text: string }) {
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  return (
    <button
      type="button"
      onClick={async () => { setState((await copyText(text)) ? 'copied' : 'failed'); setTimeout(() => setState('idle'), 1500) }}
      className="rounded-lg px-2 py-1 text-xs text-stone-500 transition hover:bg-stone-100 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      aria-label="Copy answer"
    >
      {state === 'copied' ? 'Copied' : state === 'failed' ? 'Copy failed' : 'Copy'}
    </button>
  )
}

export default function MessageView({ message, developerMode }: { message: Message; developerMode: boolean }) {
  const [highlight, setHighlight] = useState<string | null>(null)
  if (message.role === 'user') {
    return (
      <div className="flex justify-end" data-testid="user-message">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl bg-stone-200/70 px-4 py-2.5 text-[15px] leading-relaxed text-stone-900">{message.content}</div>
      </div>
    )
  }
  const r = message.result
  const cite = (marker: string) => {
    setHighlight(marker)
    const el = document.getElementById(sourceDomId(message.id, marker))
    el?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' })
    setTimeout(() => setHighlight((h) => (h === marker ? null : h)), 1800)
  }
  return (
    <div className="flex gap-3 sm:gap-4" data-testid="assistant-message">
      <div className="mt-1 hidden h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent text-[11px] font-bold text-white sm:flex" aria-hidden="true">SU</div>
      <div className="min-w-0 flex-1">
        {message.pending && <Thinking />}
        {message.error && (
          <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-900" data-testid="error-message">
            <div className="font-medium">{message.error.kind === 'offline' ? 'Service unreachable' : message.error.kind === 'timeout' ? 'Request timed out' : message.error.kind === 'malformed' ? 'Unexpected response' : 'The request failed'}</div>
            <div className="mt-0.5">{message.error.message}</div>
          </div>
        )}
        {r && r.status === 'answered' && (
          <>
            <Markdown text={r.answer} markers={new Set(r.sources.map((s) => s.marker).filter((m): m is string => !!m))} onCite={cite} />
            <Sources messageId={message.id} sources={r.sources} highlight={highlight} />
            <div className="mt-3 flex items-center gap-2">
              <CopyButton text={answerForClipboard(r.answer, r.sources)} />
              {r.metadata.grounded && <span className="text-xs text-stone-400" title="Every sentence was checked against the cited documentation text">Checked against the documentation</span>}
            </div>
          </>
        )}
        {r && r.status !== 'answered' && (
          <div className="rounded-xl border border-amber-200 bg-amber-50/70 px-4 py-3 text-[15px] text-stone-800" data-testid="status-note" data-status={r.status}>
            <div className="text-xs font-semibold uppercase tracking-wider text-amber-800">{STATUS_HEADLINE[r.status]}</div>
            <p className="mt-1 leading-relaxed">{r.answer}</p>
            {r.topic_reference && <TopicReferenceCard reference={r.topic_reference} />}
          </div>
        )}
        {r && developerMode && r.debug && <DebugPanel result={r} />}
      </div>
    </div>
  )
}
