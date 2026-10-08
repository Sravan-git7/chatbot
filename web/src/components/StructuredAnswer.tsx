import type { Source, StructuredAnswer as StructuredAnswerType } from '../types'
import Markdown from './Markdown'
import Citations from './Citations'

export interface StructuredAnswerProps {
  structuredAnswer?: StructuredAnswerType | null
  fallbackAnswer: string
  sources: Source[]
  onCite?: (marker: string) => void
}

export default function StructuredAnswer({
  structuredAnswer,
  fallbackAnswer,
  sources,
  onCite,
}: StructuredAnswerProps) {
  const markerSet = new Set(sources.map((s) => s.marker).filter((m): m is string => !!m))

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
        <Markdown text={fallbackAnswer} markers={markerSet} onCite={onCite} />
      </div>
    )
  }

  return (
    <div className="space-y-5" data-testid="structured-answer">
      {structuredAnswer!.sections.map((section, idx) => {
        const textContent =
          section.content || (section.lines ? section.lines.join('\n') : '')

        if (!textContent.trim()) {
          return null
        }

        return (
          <section
            key={`${section.key || idx}`}
            className={`space-y-1.5 ${
              idx > 0 ? 'border-t border-stone-200/60 pt-4' : ''
            }`}
            data-testid={`structured-section-${section.key || idx}`}
          >
            <div className="flex items-center justify-between gap-2 pb-1">
              <h3 className="text-[11px] font-semibold uppercase tracking-wider text-stone-500">
                {section.title || section.key}
              </h3>
              {section.citations && section.citations.length > 0 && (
                <Citations citations={section.citations} sources={sources} onCite={onCite} />
              )}
            </div>
            <div className="text-answer text-stone-900 leading-relaxed">
              <Markdown text={textContent} markers={markerSet} onCite={onCite} />
            </div>
          </section>
        )
      })}
    </div>
  )
}
