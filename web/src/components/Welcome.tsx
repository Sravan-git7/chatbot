import type { Health } from '../types'

// These prompts were verified against the real backend and the 7 locally available pages (see data/phase11_e2e_results.json).
export const EXAMPLE_PROMPTS = ['How is billing handled?', 'How do I create an installment plan?', 'How are devices managed?', 'What does monitoring of meter reading results do?']

export default function Welcome({ onPick, disabled, health }: { onPick: (q: string) => void; disabled: boolean; health: Health | null }) {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col items-center justify-center px-4 py-10 text-center">
      <div className="mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent text-sm font-bold text-white" aria-hidden="true">SU</div>
      <h1 className="text-3xl font-semibold tracking-tight text-stone-900 sm:text-4xl">Ask SAP Utilities anything.</h1>
      <p className="mt-3 max-w-xl text-[15px] leading-relaxed text-stone-600">Answers are generated from the available SAP Utilities documentation.</p>
      {health?.ready && health.pages_available != null && health.topics != null && (
        <p className="mt-1 text-xs text-stone-400" data-testid="coverage">Currently {health.pages_available} of {health.topics} documentation pages are available.</p>
      )}
      {health === null && <p className="mt-2 text-xs text-red-700" role="alert" data-testid="offline-note">The RAG service is not reachable. Start the backend, then reload.</p>}
      <div className="mt-8 grid w-full max-w-2xl grid-cols-1 gap-2.5 sm:grid-cols-2">
        {EXAMPLE_PROMPTS.map((p) => (
          <button key={p} type="button" disabled={disabled} onClick={() => onPick(p)} className="rounded-2xl border border-stone-200 bg-white px-4 py-3 text-left text-sm text-stone-800 shadow-sm transition enabled:hover:border-stone-300 enabled:hover:bg-stone-50 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}
