import { useState } from 'react'
import type { Source, TopicReference } from '../types'
import { copyText, displayUrl, groupSources, isHttpUrl } from '../util'

export function sourceDomId(messageId: string, marker: string): string {
  return `src-${messageId}-${marker}`
}

export function Sources({
  messageId,
  sources,
  highlight,
}: {
  messageId: string
  sources: Source[]
  highlight?: string | null
}) {
  const groups = groupSources(sources)
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null)

  if (!groups.length) return null

  const onCopyUrl = async (url: string) => {
    if (await copyText(url)) {
      setCopiedUrl(url)
      setTimeout(() => setCopiedUrl((cur) => (cur === url ? null : cur)), 1500)
    }
  }

  return (
    <section aria-label="Sources" className="mt-6 sm:mt-7 sura-sources-reveal">
      <div className="mb-2.5 flex items-center justify-between">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
          Sources · {groups.length}
        </h3>
        <span className="text-[11px] font-medium text-stone-400">
          SAP Help Portal
        </span>
      </div>
      <ul className={groups.length > 1 ? 'grid gap-2.5 lg:grid-cols-2 lg:auto-rows-min' : 'space-y-2.5'}>
        {groups.map((g) => {
          const active = !!highlight && g.markers.includes(highlight)
          const hasValidUrl = isHttpUrl(g.url)
          const isCopied = hasValidUrl && copiedUrl === g.url
          return (
            <li
              key={g.key}
              tabIndex={-1}
              className={`group rounded-xl border p-3.5 text-xs transition-all duration-150 outline-none sm:p-4 shadow-2xs ${
                active
                  ? 'border-accent bg-accent-soft ring-2 ring-accent/20 shadow-xs sura-cite-active'
                  : 'border-stone-200/90 bg-white hover:border-stone-300'
              }`}
              data-testid="source-item"
            >
              {g.markers.map((m) => (
                <span key={m} id={sourceDomId(messageId, m)} />
              ))}
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-2.5">
                  <span className="mt-0.5 flex shrink-0 gap-1">
                    {g.markers.map((m) => (
                      <span key={m} className="cite-chip cite-chip-static">
                        {m.slice(1)}
                      </span>
                    ))}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold leading-snug text-stone-900">{g.title}</div>
                    {g.section && g.section !== g.title && (
                      <div className="mt-0.5 text-[11px] leading-relaxed text-stone-500">
                        {g.section}
                      </div>
                    )}
                    {hasValidUrl ? (
                      <a
                        href={g.url!}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-1.5 inline-flex max-w-full items-center gap-1.5 text-xs text-accent underline-offset-2 hover:underline"
                        title={g.url!}
                      >
                        <span className="truncate">{displayUrl(g.url!)}</span>
                        <span aria-hidden="true" className="shrink-0 text-[11px] opacity-80">
                          · Open source ↗
                        </span>
                      </a>
                    ) : (
                      <span className="mt-1 block text-[11px] text-stone-400">
                        No URL available for this source
                      </span>
                    )}
                  </div>
                </div>

                {hasValidUrl && (
                  <button
                    type="button"
                    aria-label="Copy source link"
                    onClick={() => onCopyUrl(g.url!)}
                    className="shrink-0 rounded-lg border border-stone-200 bg-stone-50/80 px-2.5 py-1 text-[11px] font-medium text-stone-600 transition hover:border-accent/60 hover:bg-white hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
                  >
                    {isCopied ? 'Copied' : 'Copy link'}
                  </button>
                )}
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
    <section
      aria-label="Related SAP Help topic"
      className="mt-4 rounded-xl border border-dashed border-stone-300 bg-white/70 p-3.5 text-xs"
    >
      <div className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
        Related SAP Help topic
      </div>
      <a
        href={reference.url}
        target="_blank"
        rel="noopener noreferrer"
        className="mt-1 block font-medium text-accent underline-offset-2 hover:underline"
      >
        {reference.title} ↗
      </a>
      <div className="mt-1 text-stone-500">
        Reference only: this page is not in the local knowledge base and was not used to answer.
      </div>
    </section>
  )
}
