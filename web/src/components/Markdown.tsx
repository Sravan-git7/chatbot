import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { copyText } from '../util'

interface Props {
  text: string
  /** markers that exist as sources of this message; only these become citation chips */
  markers: Set<string>
  onCite?: (marker: string) => void
}

const CITE = /\[(S\d+)\]/g

/**
 * Safe Markdown rendering:
 *  - raw HTML is dropped (`skipHtml`; no rehype-raw), so model or page text can never inject markup;
 *  - links and images in the text are NOT rendered as links/images (clickable URLs come only from the backend `sources`);
 *  - the only interactive element is a citation chip for a marker that really is a source of this answer.
 */
const FENCE = /^\s*(```|~~~)/
const BLOCK = /^\s*(?:[-*+]\s|\d+[.)]\s|\||#{1,6}\s|>)/

export function prepare(text: string): string {
  // The extractive generator returns one cited sentence per line: such plain lines become separate paragraphs.
  // Markdown structure (lists, tables, headings, quotes, fenced code) is left exactly as written.
  const lines = text.replace(/\r\n/g, '\n').split('\n')
  const out: string[] = []
  let fenced = false
  lines.forEach((line, i) => {
    if (FENCE.test(line)) {
      fenced = !fenced
      out.push(line)
      return
    }
    if (fenced) {
      out.push(line)
      return
    }
    out.push(line.replace(CITE, '[$1](#cite-$1)'))
    const next = lines[i + 1]
    if (line.trim() && next !== undefined && next.trim() && !FENCE.test(next) && !BLOCK.test(line) && !BLOCK.test(next)) out.push('')
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

function MarkdownView({ text, markers, onCite }: Props) {
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
              return (
                <button type="button" className="cite-chip" aria-label={`Source ${m.slice(1)}`} onClick={() => onCite?.(m)}>
                  {m.slice(1)}
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
