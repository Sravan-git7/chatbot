import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import DebugPanel from '../components/DebugPanel'
import { json, mockMatchMedia, result, stubBackend } from './helpers'

const ABSTAIN = "I couldn't find enough verified information in the available SAP Utilities documentation to answer that specific detail."
const UNVERIFIED = "I couldn't verify the relevant documentation."
const composer = () => screen.getByRole('textbox')

beforeEach(() => { localStorage.clear(); mockMatchMedia(true) })
afterEach(() => { vi.unstubAllGlobals() })

const base = (status: 'unable_to_verify' | 'documentation_unavailable', answer: string, pipeline_status: string) =>
  result({ status, answer, sources: [], metadata: { ...result().metadata, grounded: false, pipeline_status, grounding: { checked: false, ok: null, sentences: 0, violations: 0, cited_markers: [] } } })

describe('abstention is shown as an abstention', () => {
  it('shows the exact abstention message, no sources, no "here is what I found" framing', async () => {
    stubBackend(() => json(base('unable_to_verify', ABSTAIN, 'insufficient_context')))
    render(<App />)
    await userEvent.type(composer(), 'What is the minimum installment amount?{Enter}')
    const note = await screen.findByTestId('status-note')
    expect(note).toHaveTextContent(ABSTAIN)
    expect(note).toHaveAttribute('data-status', 'unable_to_verify')
    expect(note.textContent).not.toMatch(/here'?s what i found|M2C-|chunk/i)
    expect(screen.queryAllByTestId('source-item')).toHaveLength(0)
    expect(screen.queryByText(/Checked against the documentation/)).not.toBeInTheDocument()
  })

  it('shows the unverified-identity text and the documentation-unavailable headline', async () => {
    let n = 0
    stubBackend(() => json(n++ === 0 ? base('unable_to_verify', UNVERIFIED, 'unresolved_identity')
      : base('documentation_unavailable', 'I found the relevant topic, but the underlying SAP Help page is not currently available in the local knowledge base.', 'page_not_ingested')))
    render(<App />)
    await userEvent.type(composer(), 'one{Enter}')
    expect(await screen.findByText(UNVERIFIED)).toBeInTheDocument()
    await userEvent.type(composer(), 'two{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('status-note')).toHaveLength(2))
    expect(screen.getAllByTestId('status-note')[1]).toHaveTextContent('Documentation unavailable')
  })
})

describe('evidence block in developer details', () => {
  const dbg = { routing: { candidates: [] }, pipeline: {}, topic: {}, timings_ms: {},
    evidence: { supported: false, reason: 'KIND_NOT_IN_EVIDENCE', kinds: ['limit'], asked_terms: [], focus_terms: ['install', 'amount'], selected: [], support_chain: { ok: true } } }

  it('renders the evidence verdict when the backend returned one', () => {
    render(<DebugPanel result={result({ debug: dbg })} />)
    const ev = screen.getByTestId('debug-evidence')
    expect(ev).toHaveTextContent('KIND_NOT_IN_EVIDENCE')
    expect(ev).toHaveTextContent('install, amount')
  })

  it('renders no evidence block when there is none (old backend / non-debug)', () => {
    render(<DebugPanel result={result({ debug: { ...dbg, evidence: null } })} />)
    expect(screen.queryByTestId('debug-evidence')).not.toBeInTheDocument()
  })
})
