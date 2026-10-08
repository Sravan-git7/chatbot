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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-xs p-4" onClick={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Settings and about"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl border border-stone-200/90 bg-white p-6 shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between border-b border-stone-100 pb-3">
          <div>
            <h2 className="text-base font-semibold text-stone-900">Settings &amp; about</h2>
            <p className="text-xs text-stone-500">SURA · SAP Utilities Assistant</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-100 hover:text-stone-700 cursor-pointer"
          >
            ✕
          </button>
        </div>
        <div className="mt-4 space-y-3.5 text-xs leading-relaxed text-stone-600">
          <p>
            Answers come from the local retrieval pipeline over the SAP Utilities documentation pages stored on the server. Every answer lists the pages it was taken from, and the assistant says so when it cannot answer.
          </p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3.5 gap-y-1.5 rounded-xl border border-stone-200/70 bg-[#faf9f6] p-3 text-xs" data-testid="service-info">
            <dt className="font-medium text-stone-500">Service</dt>
            <dd className="font-semibold text-stone-800">{health === null ? 'unreachable' : health.ready ? 'ready' : `not ready${health.reason ? `: ${health.reason}` : ''}`}</dd>
            <dt className="font-medium text-stone-500">Generator</dt>
            <dd className="text-stone-700">{health?.generator ? (health.generator === 'extractive' ? 'extractive' : health.generator) : '-'}</dd>
            <dt className="font-medium text-stone-500">Documentation</dt>
            <dd className="text-stone-700">{health?.pages_available != null && health.topics != null ? `${health.pages_available} of ${health.topics} topic pages available` : '-'}</dd>
          </dl>
          <p className="text-stone-500">
            Questions about the other topics are answered with "documentation unavailable". Each question is answered on its own. Your conversations are stored in this browser (local storage) only.
          </p>
        </div>
        <div className="mt-5 border-t border-stone-100 pt-4">
          <label className="flex cursor-pointer items-start gap-3 text-xs text-stone-800">
            <input
              type="checkbox"
              className="mt-0.5 h-4 w-4 rounded accent-accent cursor-pointer"
              checked={settings.developerMode}
              onChange={(e) => onSettings({ ...settings, developerMode: e.target.checked })}
            />
            <div>
              <span className="font-semibold text-stone-900">Developer details</span>
              <p className="mt-0.5 text-stone-500">Show routing, retrieval, grounding and latency under each answer.</p>
            </div>
          </label>
        </div>
        <div className="mt-5 border-t border-stone-100 pt-4">
          <button
            type="button"
            onClick={() => { if (window.confirm('Delete all conversations stored in this browser?')) onClearAll() }}
            className="rounded-lg border border-red-200 bg-red-50/50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100/60 cursor-pointer transition"
          >
            Delete all conversations
          </button>
        </div>
      </div>
    </div>
  )
}
