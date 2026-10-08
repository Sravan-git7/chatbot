import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { copyText, normalizeDisplayText } from '../util'

interface Props {
  text: string
  /** markers that exist as sources of this message; only these become citation chips */
  markers: Set<string>
  markerMap?: Record<string, number>
  onCite?: (marker: string) => void
}

const CITE = /\[(S\d+)\]/g
const TRAILING_CITE = /\s*\[(S\d+)\]\s*$/

/**
 * Safe Markdown rendering:
 *  - raw HTML is dropped (`skipHtml`; no rehype-raw), so model or page text can never inject markup;
 *  - links and images in the text are NOT rendered as links/images (clickable URLs come only from the backend `sources`);
 *  - the only interactive element is a citation chip for a marker that really is a source of this answer.
 */
const FENCE = /^\s*(```|~~~)/
const BLOCK = /^\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|>)/

export function prepare(text: string): string {
  // Collapse consecutive duplicate citation markers like [S1] [S1] or [S1][S1] into [S1]
  const collapsed = text.replace(/(\[(S\d+)\])(?:\s*\1)+/g, '$1')
  // Display-safe whitespace normalization (extraction artifacts only; citation spans are untouched)
  const normalized = normalizeDisplayText(collapsed)
  const lines = normalized.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let fenced = false
  let prevTrailing: string | null = null
  lines.forEach((line, i) => {
    if (FENCE.test(line)) {
      fenced = !fenced
      out.push(line)
      prevTrailing = null
      return
    }
    if (fenced) {
      out.push(line)
      return
    }
    let content = line
    // A line whose only citation is the same marker as the immediately preceding line does not repeat the chip;
    // the underlying citation mapping (markerMap, sources) is unchanged.
    const trailing = TRAILING_CITE.exec(content)
    if (trailing && trailing[1] === prevTrailing && !new RegExp(`\\[${trailing[1]}\\]`).test(content.slice(0, trailing.index))) {
      content = content.slice(0, trailing.index)
    }
    prevTrailing = trailing ? trailing[1] : null
    out.push(content.replace(CITE, '[$1](#cite-$1)'))
    const next = lines[i + 1]
    if (content.trim() && next !== undefined && next.trim() && !FENCE.test(next) && !BLOCK.test(content) && !BLOCK.test(next)) out.push('')
  })
  return out.join('\n')
}

function CodeBlock({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const text = (() => {
    const kids = Array.isArray(children) ? children : [children]
    return kids.map((k) => (typeof k === 'string' ? k : (k as { props?: { children?: unknown } })?.props?.children)).flat().join('')
  })()
  return (
    <div className="group relative my-4 overflow-hidden rounded-xl border border-stone-200 bg-stone-50">
      <button
        type="button"
        aria-label="Copy code"
        onClick={async () => { if (await copyText(String(text).replace(/\n$/, ''))) { setCopied(true); setTimeout(() => setCopied(false), 1500) } }}
        className="absolute right-2 top-2 rounded-md border border-stone-200 bg-white px-2 py-1 text-xs text-stone-600 opacity-0 transition hover:bg-stone-100 focus:opacity-100 group-hover:opacity-100"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
      <pre className="overflow-x-auto p-4 text-[13px] leading-relaxed text-stone-800">{children}</pre>
    </div>
  )
}

function MarkdownView({ text, markers, markerMap, onCite }: Props) {
  return (
    <div className="prose-chat">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => (url.startsWith('#cite-') ? url : '')}
        components={{
          a: ({ href, children }) => {
            const m = href?.startsWith('#cite-') ? href.slice(6) : null
            if (m && markers.has(m)) {
              const displayNum = markerMap && markerMap[m] !== undefined ? markerMap[m] : (m.startsWith('S') ? m.slice(1) : m)
              return (
                <button
                  type="button"
                  className="cite-chip cursor-pointer focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  aria-label={`Source ${displayNum}`}
                  onClick={() => onCite?.(m)}
                >
                  {displayNum}
                </button>
              )
            }
            return <span>{m ? `[${m}]` : children}</span>
          },
          img: () => null,
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          table: ({ children }) => <div className="my-4 overflow-x-auto"><table>{children}</table></div>,
        }}
      >
        {prepare(text)}
      </ReactMarkdown>
    </div>
  )
}

export default memo(MarkdownView)
