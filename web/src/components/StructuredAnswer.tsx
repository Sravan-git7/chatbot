import type { Source, StructuredAnswer as StructuredAnswerType } from '../types'
import { citationDisplayMap } from '../util'
import Markdown from './Markdown'

export interface StructuredAnswerProps {
  structuredAnswer?: StructuredAnswerType | null
  fallbackAnswer: string
  sources: Source[]
  markerMap?: Record<string, number>
  onCite?: (marker: string) => void
  isElaboration?: boolean
}

function sectionText(section: StructuredAnswerType['sections'][number]): string {
  return section.content || (section.lines ? section.lines.join('\n') : '')
}

/** The marker order must follow the content that is actually rendered, not a potentially differently ordered fallback. */
export function visibleAnswerText(
  structuredAnswer: StructuredAnswerType | null | undefined,
  fallbackAnswer: string,
): string {
  const sections = structuredAnswer?.sections
  if (!Array.isArray(sections) || !sections.some((section) => sectionText(section).trim())) return fallbackAnswer
  return sections.map(sectionText).filter((text) => text.trim()).join('\n')
}

export function buildMarkerMap(text: string, sources?: Source[]): Record<string, number> {
  return citationDisplayMap(text, sources)
}

export default function StructuredAnswer({
  structuredAnswer,
  fallbackAnswer,
  sources,
  markerMap: customMarkerMap,
  onCite,
  isElaboration = false,
}: StructuredAnswerProps) {
  const markerSet = new Set(sources.map((source) => source.marker).filter((marker): marker is string => !!marker))
  const displayText = visibleAnswerText(structuredAnswer, fallbackAnswer)
  const markerMap = customMarkerMap ?? buildMarkerMap(displayText, sources)
  const sections = structuredAnswer?.sections
  const hasValidStructured = Array.isArray(sections) && sections.some((section) => sectionText(section).trim().length > 0)

  if (!hasValidStructured) {
    return (
      <div data-testid="canonical-answer-fallback" className="leading-relaxed">
        {isElaboration && (
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-stone-500" data-testid="elaboration-section-title">
            Additional detail
          </h3>
        )}
        <Markdown text={fallbackAnswer} markers={markerSet} markerMap={markerMap} onCite={onCite} />
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="structured-answer">
      {sections!.map((section, index) => {
        const textContent = sectionText(section)
        if (!textContent.trim()) return null
        const title = isElaboration && index === 0 ? 'Additional detail' : section.title || section.key
        return (
          <section
            key={`${section.key || index}`}
            className={`space-y-1 ${index > 0 ? 'border-t border-stone-200/60 pt-3.5' : ''}`}
            data-testid={`structured-section-${section.key || index}`}
          >
            <div className="pb-0.5">
              <h3
                className="text-[11px] font-semibold uppercase tracking-wider text-stone-500"
                data-testid={isElaboration && index === 0 ? 'elaboration-section-title' : undefined}
              >
                {title}
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
