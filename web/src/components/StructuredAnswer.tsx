import type { ElaborationSection, ElaborationSectionKey, Source, StructuredAnswer as StructuredAnswerType } from '../types'
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

const ELABORATION_SECTION_TITLES: Record<ElaborationSectionKey, string> = {
  what_it_is_does: 'What it is / does',
  how_it_works_relationships: 'How it works',
  conditions_prerequisites: 'Prerequisites',
  key_details: 'Key details',
}

/** Use backend-validated elaboration groups only when they reconstruct the canonical, cited answer exactly. */
export function structuredElaborationAnswer(
  presentationSections: ElaborationSection[] | undefined,
  canonicalAnswer: string,
): StructuredAnswerType | null {
  if (!Array.isArray(presentationSections) || presentationSections.length === 0 || !canonicalAnswer) return null
  const canonicalLines = canonicalAnswer.split('\n')
  const orderedLines = new Map<number, { line: string; key: ElaborationSectionKey }>()
  const seenKeys = new Set<string>()

  for (const section of presentationSections) {
    if (!section || !Object.prototype.hasOwnProperty.call(ELABORATION_SECTION_TITLES, section.key) || seenKeys.has(section.key)) return null
    if (!Array.isArray(section.lines) || section.lines.length === 0 || !Array.isArray(section.line_orders)
      || section.line_orders.length !== section.lines.length) return null
    seenKeys.add(section.key)
    section.lines.forEach((line, index) => {
      const order = section.line_orders![index]
      if (typeof line !== 'string' || !line.trim() || !Number.isInteger(order) || order < 0 || order >= canonicalLines.length
        || orderedLines.has(order) || canonicalLines[order] !== line) return
      orderedLines.set(order, { line, key: section.key })
    })
    if (section.lines.some((line, index) => typeof line !== 'string' || !line.trim()
      || !Number.isInteger(section.line_orders![index]) || section.line_orders![index] < 0
      || section.line_orders![index] >= canonicalLines.length)) return null
  }

  if (orderedLines.size !== canonicalLines.length) return null
  const orderedEntries = canonicalLines.map((_line, index) => orderedLines.get(index))
  if (orderedEntries.some((entry, index) => !entry || entry.line !== canonicalLines[index])) return null

  // Category sections may have been grouped globally, but their line_orders are authoritative. Rebuild contiguous
  // sections in canonical source order so a semantic grouping never moves a cited fact ahead of its source neighbors.
  const sections: StructuredAnswerType['sections'] = []
  const titledKeys = new Set<ElaborationSectionKey>()
  for (const entry of orderedEntries) {
    if (!entry) return null
    const previous = sections[sections.length - 1]
    if (previous?.key === entry.key) {
      previous.lines = [...(previous.lines ?? []), entry.line]
      previous.content = [...(previous.lines ?? [])].join('\n')
      for (const match of entry.line.matchAll(/\[(S\d+)\]/g)) {
        previous.citations = previous.citations ?? []
        if (!previous.citations.includes(match[1])) previous.citations.push(match[1])
      }
      continue
    }
    const citations = Array.from(entry.line.matchAll(/\[(S\d+)\]/g), (match) => match[1])
    const showTitle = !titledKeys.has(entry.key)
    titledKeys.add(entry.key)
    sections.push({
      title: showTitle ? ELABORATION_SECTION_TITLES[entry.key] : '',
      key: entry.key,
      lines: [entry.line],
      content: entry.line,
      citations: [...new Set(citations)],
      showTitle,
    })
  }

  const citations: string[] = []
  for (const line of canonicalLines) {
    for (const match of line.matchAll(/\[(S\d+)\]/g)) {
      if (!citations.includes(match[1])) citations.push(match[1])
    }
  }
  return { summary: canonicalLines[0], sections, citations }
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
  const firstVisibleTitleIndex = Array.isArray(sections)
    ? sections.findIndex((section) => section.showTitle !== false && sectionText(section).trim().length > 0)
    : -1
  const firstSectionKey = firstVisibleTitleIndex >= 0 ? sections?.[firstVisibleTitleIndex]?.key : undefined
  const hasSemanticElaborationSections = isElaboration
    && !!firstSectionKey
    && Object.prototype.hasOwnProperty.call(ELABORATION_SECTION_TITLES, firstSectionKey)

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
        const showTitle = section.showTitle !== false
        const title = isElaboration && index === firstVisibleTitleIndex && !hasSemanticElaborationSections
          ? 'Additional detail'
          : section.title || section.key
        return (
          <section
            key={`${section.key || 'section'}-${index}`}
            className={`space-y-1 ${index > 0 ? 'border-t border-stone-200/60 pt-3.5' : ''}`}
            data-testid={`structured-section-${section.key || index}-${index}`}
          >
            {showTitle && (
              <div className="pb-0.5">
                <h3
                  className="text-[11px] font-semibold uppercase tracking-wider text-stone-500"
                  data-testid={isElaboration && index === firstVisibleTitleIndex ? 'elaboration-section-title' : undefined}
                >
                  {title}
                </h3>
              </div>
            )}
            <div className="text-answer text-stone-900 leading-relaxed">
              <Markdown text={textContent} markers={markerSet} markerMap={markerMap} onCite={onCite} />
            </div>
          </section>
        )
      })}
    </div>
  )
}
