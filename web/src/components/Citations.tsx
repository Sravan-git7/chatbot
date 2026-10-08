import type { Source } from '../types'

export interface CitationsProps {
  citations: string[]
  sources?: Source[]
  markerMap?: Record<string, number>
  onCite?: (marker: string) => void
}

export default function Citations({ citations, sources, markerMap, onCite }: CitationsProps) {
  if (!citations || citations.length === 0) {
    return null
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-1 align-baseline text-xs" data-testid="citations-container">
      {citations.map((marker) => {
        const source = sources?.find((s) => s.marker === marker)
        const label = markerMap && markerMap[marker] !== undefined ? markerMap[marker] : (marker.startsWith('S') ? marker.slice(1) : marker)
        return (
          <button
            key={marker}
            type="button"
            onClick={() => onCite?.(marker)}
            title={source ? `${source.title || ''} (${source.section || ''})` : `Source ${marker}`}
            className="cite-chip cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            data-testid={`citation-${marker}`}
            aria-label={`Source ${label}`}
          >
            {label}
          </button>
        )
      })}
    </span>
  )
}
