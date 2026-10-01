import { useEffect, useRef } from 'react'
import type { Health, Settings } from '../types'

interface Props {
  health: Health | null
  settings: Settings
  onSettings: (s: Settings) => void
  onClearAll: () => void
  onClose: () => void
}

export default function AboutPanel({ health, settings, onSettings, onClearAll, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/30 p-4" onClick={onClose}>
      <div ref={ref} tabIndex={-1} role="dialog" aria-modal="true" aria-label="Settings and about" onClick={(e) => e.stopPropagation()} className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl bg-white p-6 shadow-2xl outline-none">
        <div className="flex items-start justify-between">
          <h2 className="text-lg font-semibold text-stone-900">Settings &amp; about</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="-mr-2 -mt-2 rounded-lg p-2 text-stone-500 hover:bg-stone-100">✕</button>
        </div>
        <div className="mt-4 space-y-3 text-sm leading-relaxed text-stone-700">
          <p>Answers come from the local retrieval pipeline over the SAP Utilities documentation pages stored on the server. Every answer lists the pages it was taken from, and the assistant says so when it cannot answer.</p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 rounded-xl bg-stone-50 p-3 text-[13px]" data-testid="service-info">
            <dt className="text-stone-500">Service</dt>
            <dd>{health === null ? 'unreachable' : health.ready ? 'ready' : `not ready${health.reason ? `: ${health.reason}` : ''}`}</dd>
            <dt className="text-stone-500">Generator</dt>
            <dd>{health?.generator ? (health.generator === 'extractive' ? 'extractive (sentences copied from the documentation; no language model)' : health.generator) : '-'}</dd>
            <dt className="text-stone-500">Documentation</dt>
            <dd>{health?.pages_available != null && health.topics != null ? `${health.pages_available} of ${health.topics} topic pages available` : '-'}</dd>
          </dl>
          <p>Questions about the other topics are answered with "documentation unavailable". Each question is answered on its own: there is no memory of earlier messages. Your conversations are stored in this browser (local storage) and nowhere else.</p>
        </div>
        <label className="mt-4 flex cursor-pointer items-start gap-3 text-sm text-stone-800">
          <input type="checkbox" className="mt-1 h-4 w-4 accent-[#0b6e5f]" checked={settings.developerMode} onChange={(e) => onSettings({ ...settings, developerMode: e.target.checked })} />
          <span><span className="font-medium">Developer details</span><br /><span className="text-stone-500">Show routing, retrieval, grounding and latency under each answer. Does not change answers.</span></span>
        </label>
        <button type="button" onClick={() => { if (window.confirm('Delete all conversations stored in this browser?')) onClearAll() }} className="mt-5 rounded-lg border border-stone-300 px-3 py-1.5 text-sm text-stone-700 hover:bg-stone-50">
          Delete all conversations
        </button>
      </div>
    </div>
  )
}
