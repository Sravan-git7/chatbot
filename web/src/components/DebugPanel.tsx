import type { ChatResult } from '../types'

type Obj = Record<string, unknown>
const asObj = (x: unknown): Obj => (x && typeof x === 'object' ? (x as Obj) : {})
const asArr = (x: unknown): Obj[] => (Array.isArray(x) ? (x as Obj[]) : [])
const fmt = (x: unknown) => (typeof x === 'number' ? (Number.isInteger(x) ? String(x) : x.toFixed(4)) : x == null ? '-' : String(x))

/** Developer view. Read-only: it renders what the backend returned in `debug` and never alters the answer. */
export default function DebugPanel({ result }: { result: ChatResult }) {
  const d = asObj(result.debug)
  const routing = asObj(d.routing)
  const pipeline = asObj(d.pipeline)
  const topic = asObj(d.topic)
  const grounding = asObj(pipeline.grounding)
  const generation = asObj(pipeline.generation)
  const timings = asObj(d.timings_ms)
  const chain = asArr(asObj(d.citations).answer_sources)
  const candidates = asArr(routing.candidates)
  const retrieved = asArr(pipeline.retrieved)
  const evidence = asObj(d.evidence)
  const hasEvidence = Object.keys(evidence).length > 0
  const evSelected = asArr(evidence.selected)
  const evChain = asObj(evidence.support_chain)
  const evList = (x: unknown) => (Array.isArray(x) && x.length ? x.map(String).join(', ') : '-')
  return (
    <details className="mt-4 rounded-xl border border-stone-200 bg-stone-50 text-xs text-stone-700" data-testid="debug-panel">
      <summary className="cursor-pointer select-none px-3 py-2 font-medium text-stone-600">Developer details</summary>
      <div className="space-y-3 border-t border-stone-200 p-3 font-mono">
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
          <dt>pipeline status</dt><dd>{result.metadata.pipeline_status} {result.metadata.reason_code ? `(${result.metadata.reason_code})` : ''}</dd>
          <dt>card</dt><dd>{fmt(topic.source_id)} {fmt(topic.title)}</dd>
          <dt>identity</dt><dd>{fmt(topic.identity_status)}</dd>
          <dt>page</dt><dd>{fmt(topic.effective_guide_id)} / {fmt(topic.effective_page_id)} ({fmt(topic.corpus_status)})</dd>
          <dt>generator</dt><dd>{fmt(generation.generator ?? result.metadata.generator)}</dd>
          <dt>grounding</dt><dd>ok={fmt(grounding.ok)} cited={asArr(grounding.cited_markers).length ? JSON.stringify(grounding.cited_markers) : '[]'} violations={asArr(grounding.violations).length}</dd>
          <dt>latency</dt><dd>total {fmt(timings.total_ms)} ms · route {fmt(timings.route_ms)} · retrieve {fmt(timings.retrieve_ms)} · generate {fmt(timings.generate_ms)}</dd>
        </dl>
        {candidates.length > 0 && (
          <div>
            <div className="mb-1 font-semibold">Card routing</div>
            <table className="w-full text-left"><thead><tr><th>rank</th><th>card</th><th>similarity</th><th>distance</th></tr></thead>
              <tbody>{candidates.map((c) => <tr key={String(c.source_id)}><td>{fmt(c.rank)}</td><td>{fmt(c.source_id)} {fmt(c.title)}</td><td>{fmt(c.similarity)}</td><td>{fmt(c.distance)}</td></tr>)}</tbody></table>
          </div>
        )}
        {retrieved.length > 0 && (
          <div>
            <div className="mb-1 font-semibold">Retrieved chunks</div>
            <table className="w-full text-left"><thead><tr><th>#</th><th>chunk</th><th>similarity</th></tr></thead>
              <tbody>{retrieved.map((c, i) => <tr key={i}><td>{fmt(c.rank)}</td><td className="break-all">{fmt(c.chunk_id)}</td><td>{fmt(c.similarity)}</td></tr>)}</tbody></table>
          </div>
        )}
        {hasEvidence && (
          <div data-testid="debug-evidence">
            <div className="mb-1 font-semibold">Evidence check</div>
            <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1">
              <dt>supported</dt><dd>{fmt(evidence.supported)} {evidence.reason ? `(${fmt(evidence.reason)})` : ''}</dd>
              <dt>needs</dt><dd>{evList(evidence.kinds)} · asked: {evList(evidence.asked_terms)}</dd>
              <dt>focus terms</dt><dd>{evList(evidence.focus_terms)}</dd>
              <dt>support chain</dt><dd>{evChain.ok === undefined ? '-' : fmt(evChain.ok)}</dd>
            </dl>
            {evSelected.length > 0 && (
              <ul className="mt-1 space-y-1">{evSelected.map((c, i) => <li key={i} className="break-all">[{fmt(c.marker)}] {fmt(c.chunk_id)} · coverage {fmt(c.coverage)}</li>)}</ul>
            )}
          </div>
        )}
        {chain.length > 0 && (
          <div>
            <div className="mb-1 font-semibold">Citation chain</div>
            <ul className="space-y-1">{chain.map((c, i) => <li key={i} className="break-all">[{fmt(c.marker)}] {fmt(c.chunk_id)} → joined to card {fmt(asObj(c.join).card_source_id)} by {fmt(asObj(c.join).by)}</li>)}</ul>
          </div>
        )}
      </div>
    </details>
  )
}
