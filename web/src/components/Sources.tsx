import type { Source, TopicReference } from '../types'
import { displayUrl, groupSources, isHttpUrl } from '../util'

export function sourceDomId(messageId: string, marker: string): string {
  return `src-${messageId}-${marker}`
}

export function Sources({ messageId, sources, highlight }: { messageId: string; sources: Source[]; highlight?: string | null }) {
  const groups = groupSources(sources)
  if (!groups.length) return null
  return (
    <section aria-label="Sources" className="mt-5">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-stone-500">Sources</h3>
      <ul className="space-y-2">
        {groups.map((g) => {
          const active = !!highlight && g.markers.includes(highlight)
          return (
            <li key={g.key} className={`rounded-xl border px-3 py-2.5 text-sm transition-colors ${active ? 'border-accent bg-accent-soft' : 'border-stone-200 bg-white'}`} data-testid="source-item">
              {g.markers.map((m) => <span key={m} id={sourceDomId(messageId, m)} />)}
              <div className="flex items-start gap-2">
                <span className="mt-0.5 flex shrink-0 gap-1">
                  {g.markers.map((m) => <span key={m} className="cite-chip cite-chip-static">{m.slice(1)}</span>)}
                </span>
                <div className="min-w-0">
                  <div className="font-medium text-stone-800">{g.title}</div>
                  {g.section && g.section !== g.title && <div className="text-stone-500">{g.section}</div>}
                  {isHttpUrl(g.url) ? (
                    <a href={g.url} target="_blank" rel="noopener noreferrer" className="mt-0.5 block truncate text-accent underline-offset-2 hover:underline" title={g.url}>
                      {displayUrl(g.url)}
                    </a>
                  ) : (
                    <span className="mt-0.5 block text-stone-400">No URL available for this source</span>
                  )}
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

export function TopicReferenceCard({ reference }: { reference: TopicReference }) {
  if (!isHttpUrl(reference.url)) return null
  return (
    <section aria-label="Related SAP Help topic" className="mt-4 rounded-xl border border-dashed border-stone-300 bg-white/60 px-3 py-2.5 text-sm">
      <div className="text-xs font-semibold uppercase tracking-wider text-stone-500">Related SAP Help topic</div>
      <a href={reference.url} target="_blank" rel="noopener noreferrer" className="mt-1 block font-medium text-accent underline-offset-2 hover:underline">
        {reference.title}
      </a>
      <div className="mt-0.5 text-stone-500">Reference only: this page is not in the local knowledge base and was not used to answer.</div>
    </section>
  )
}
