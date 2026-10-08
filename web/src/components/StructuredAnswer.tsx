import type { Source, StructuredAnswer as StructuredAnswerType } from '../types'
import Markdown from './Markdown'

export interface StructuredAnswerProps {
  structuredAnswer?: StructuredAnswerType | null
  fallbackAnswer: string
  sources: Source[]
  markerMap?: Record<string, number>
  onCite?: (marker: string) => void
}

export function buildMarkerMap(text: string): Record<string, number> {
  const map: Record<string, number> = {}
  const regex = /\[(S\d+)\]/g
  let match: RegExpExecArray | null
  let count = 1
  while ((match = regex.exec(text)) !== null) {
    const marker = match[1]
    if (map[marker] === undefined) {
      map[marker] = count++
    }
  }
  return map
}

export default function StructuredAnswer({
  structuredAnswer,
  fallbackAnswer,
  sources,
  markerMap: customMarkerMap,
  onCite,
}: StructuredAnswerProps) {
  const markerSet = new Set(sources.map((s) => s.marker).filter((m): m is string => !!m))
  const markerMap = customMarkerMap ?? buildMarkerMap(fallbackAnswer)

  // Validate that structuredAnswer exists and contains non-empty sections
  const hasValidStructured =
    structuredAnswer &&
    Array.isArray(structuredAnswer.sections) &&
    structuredAnswer.sections.length > 0 &&
    structuredAnswer.sections.some(
      (sec) =>
        (sec.lines && sec.lines.length > 0) ||
        (sec.content && sec.content.trim().length > 0),
    )

  if (!hasValidStructured) {
    // Canonical flat-answer fallback
    return (
      <div data-testid="canonical-answer-fallback" className="leading-relaxed">
        <Markdown text={fallbackAnswer} markers={markerSet} markerMap={markerMap} onCite={onCite} />
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="structured-answer">
      {structuredAnswer!.sections.map((section, idx) => {
        const textContent =
          section.content || (section.lines ? section.lines.join('\n') : '')

        if (!textContent.trim()) {
          return null
        }

        return (
          <section
            key={`${section.key || idx}`}
            className={`space-y-1 ${
              idx > 0 ? 'border-t border-stone-200/60 pt-3.5' : ''
            }`}
            data-testid={`structured-section-${section.key || idx}`}
          >
            <div className="pb-0.5">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                {section.title || section.key}
              </h3>
            </div>
            <div className="text-answer text-stone-900 leading-relaxed">
              <Markdown text={textContent} markers={markerSet} markerMap={markerMap} onCite={onCite} />
            </div>
          </section>
        )
      })}
    </div>
  )
}
