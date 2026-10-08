import { useEffect, useRef } from 'react'
import type { Health, Settings } from '../types'

interface Props {
  health: Health | null | undefined
  settings: Settings
  onSettings: (s: Settings) => void
  onClearAll: () => void
  onClose: () => void
}

export default function AboutPanel({ health, settings, onSettings, onClearAll, onClose }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null
    ref.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const dialog = ref.current
      const focusable = dialog?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])')
      if (!focusable?.length) {
        event.preventDefault()
        dialog?.focus()
        return
      }
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement
      if (!dialog || !dialog.contains(active) || active === dialog) {
        event.preventDefault()
        ;(event.shiftKey ? last : first).focus()
      } else if (event.shiftKey && active === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && active === last) {
        event.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      previouslyFocused?.focus()
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-stone-900/40 backdrop-blur-xs p-4" onClick={onClose}>
      <div
        ref={ref}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-labelledby="about-title"
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full max-w-md overflow-y-auto rounded-2xl border border-stone-200/90 bg-white p-6 shadow-2xl outline-none"
      >
        <div className="flex items-start justify-between border-b border-stone-100 pb-3">
          <div>
            <h2 id="about-title" className="text-base font-semibold text-stone-900">Settings &amp; about</h2>
            <p className="text-xs text-stone-500">SURA · SAP Utilities Assistant</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-stone-500 hover:bg-stone-100 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
          >
            ✕
          </button>
        </div>
        <div className="mt-4 space-y-3.5 text-xs leading-relaxed text-stone-600">
          <p>
            Answers are grounded in the SAP Utilities documentation available on this server. Grounded answers list their source pages; when a page is unavailable or the evidence is insufficient, SURA says so.
          </p>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-3.5 gap-y-1.5 rounded-xl border border-stone-200/70 bg-[#faf9f6] p-3 text-xs" data-testid="service-info">
            <dt className="font-medium text-stone-500">Service</dt>
            <dd className="font-semibold text-stone-800">{health === undefined ? 'checking' : health === null ? 'unreachable' : health.ready ? 'ready' : `not ready${health.reason ? `: ${health.reason}` : ''}`}</dd>
            <dt className="font-medium text-stone-500">Generator</dt>
            <dd className="text-stone-700">{health?.generator ? (health.generator === 'extractive' ? 'extractive' : health.generator) : '-'}</dd>
            <dt className="font-medium text-stone-500">Documentation</dt>
            <dd className="text-stone-700">{health?.pages_available != null && health.topics != null ? `${health.pages_available} of ${health.topics} documentation sources available` : '-'}</dd>
          </dl>
          <p className="text-stone-500">
            Questions about pages that are not loaded or whose identity is not verified are not answered from neighboring topics. Follow-up requests such as Elaborate build on the active answer. Your conversations are stored in this browser (local storage) only.
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
            className="rounded-lg border border-red-200 bg-red-50/50 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-100/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-red-700 cursor-pointer transition"
          >
            Delete all conversations
          </button>
        </div>
      </div>
    </div>
  )
}
