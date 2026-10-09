import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { EXAMPLE_PROMPTS } from '../components/Welcome'
import * as storage from '../storage'
import { HEALTH, SOURCE, json, mockMatchMedia, result, stubBackend } from './helpers'

const composer = () => screen.getByRole('textbox', { name: 'Message' })
const sendBtn = () => screen.getByRole('button', { name: 'Send message' })

describe('initial state', () => {
  it('shows the welcome state, the examples and the real coverage reported by the backend', async () => {
    stubBackend(() => json(result()))
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Ask about SAP Utilities documentation.' })).toBeInTheDocument()
    expect(screen.getByTestId('sura-intro')).toHaveTextContent('Documentation-grounded assistant')
    expect(screen.getByRole('heading', { name: 'Suggested questions' })).toBeInTheDocument()
    expect(screen.queryByText(/answers are generated from/i)).not.toBeInTheDocument()
    EXAMPLE_PROMPTS.forEach((p) => expect(screen.getByRole('button', { name: p })).toBeInTheDocument())
    expect(await screen.findByTestId('coverage')).toHaveTextContent('25 of 29')
    expect(sendBtn()).toBeDisabled()
  })

  it('keeps the initial health check separate from a confirmed offline state', async () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => {})))
    render(<App />)
    expect(screen.getByTestId('health-checking')).toHaveTextContent('Checking service availability')
    expect(screen.queryByTestId('offline-note')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Settings & about' }))
    expect(screen.getByTestId('service-info')).toHaveTextContent('checking')
  })

  it('reports a non-ready backend separately from an unreachable backend', async () => {
    stubBackend(() => json(result()), { ...HEALTH, ready: false, reason: 'document store unavailable' })
    render(<App />)
    expect(await screen.findByTestId('notready-note')).toHaveTextContent('The RAG service is not ready')
    expect(screen.queryByTestId('offline-note')).not.toBeInTheDocument()
    expect(screen.queryByTestId('coverage')).not.toBeInTheDocument()
  })

  it('tells the user when the backend is unreachable', async () => {
    stubBackend(() => json(result()), null)
    render(<App />)
    expect(await screen.findByTestId('offline-note')).toHaveTextContent('not reachable')
    expect(await screen.findByTestId('offline-badge')).toBeInTheDocument()
  })
})

describe('sending', () => {
  it('clicking an example prompt sends exactly that text to the backend', async () => {
    const { calls } = stubBackend(() => json(result()))
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: EXAMPLE_PROMPTS[1] }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].message).toBe(EXAMPLE_PROMPTS[1])
    expect(await screen.findByTestId('assistant-message')).toBeInTheDocument()
  })

  it('sends typed text with Enter, keeps Shift+Enter as a newline, and clears the input', async () => {
    const { calls } = stubBackend(() => json(result()))
    render(<App />)
    await userEvent.type(composer(), 'line one{Shift>}{Enter}{/Shift}line two')
    expect(calls).toHaveLength(0)
    expect((composer() as HTMLTextAreaElement).value).toBe('line one\nline two')
    await userEvent.keyboard('{Enter}')
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].message).toBe('line one\nline two')
    expect((composer() as HTMLTextAreaElement).value).toBe('')
    expect(calls[0].conversation_id).toMatch(/^[0-9a-f]{32}$/)
  })

  it('does not send empty or whitespace-only input', async () => {
    const { calls } = stubBackend(() => json(result()))
    render(<App />)
    await userEvent.type(composer(), '   ')
    expect(sendBtn()).toBeDisabled()
    await userEvent.keyboard('{Enter}')
    expect(calls).toHaveLength(0)
    await userEvent.type(composer(), 'x')
    expect(sendBtn()).toBeEnabled()
  })

  it('shows an honest loading state while the request is open and blocks a second send', async () => {
    let release: (r: Response) => void = () => {}
    const { calls } = stubBackend(() => new Promise<Response>((res) => { release = res }))
    render(<App />)
    await userEvent.type(composer(), 'How is billing handled?{Enter}')
    const loading = await screen.findByTestId('loading')
    expect(loading).toHaveTextContent('Searching the SAP Utilities documentation')
    await userEvent.type(composer(), 'second')
    expect(sendBtn()).toBeDisabled()
    release(json(result()))
    await waitFor(() => expect(screen.queryByTestId('loading')).not.toBeInTheDocument())
    expect(calls).toHaveLength(1)
  })
})

describe('answers', () => {
  it('renders the backend answer, citation chips and the source list with the stored URL', async () => {
    stubBackend(() => json(result()))
    render(<App />)
    await userEvent.type(composer(), 'How do I create an installment plan?{Enter}')
    const msg = await screen.findByTestId('assistant-message')
    expect(within(msg).getByText(/Choose Account > Installment Plan > Create\./)).toBeInTheDocument()
    expect(within(msg).getAllByRole('button', { name: 'Source 1' }).length).toBeGreaterThan(0)
    const item = within(msg).getByTestId('source-item')
    expect(item).toHaveTextContent('Creating Installment Plans')
    expect(item).toHaveTextContent('Activities')
    expect(item).not.toHaveTextContent('Creating Installment Plans > Creating Installment Plans')
    const link = within(item).getByRole('link')
    expect(link).toHaveAttribute('href', SOURCE.url!)
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('clicking a citation chip highlights and scrolls to its source', async () => {
    stubBackend(() => json(result()))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const msg = await screen.findByTestId('assistant-message')
    await userEvent.click(within(msg).getAllByRole('button', { name: 'Source 1' })[0])
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
    expect(within(msg).getByTestId('source-item').className).toContain('border-accent')
  })

  it('groups chunks of the same page section into one source row', async () => {
    const two = result({ sources: [{ ...SOURCE, marker: 'S2' }, { ...SOURCE, marker: 'S3', chunk_id: 'g/p/002' }], answer: 'A. [S2]\nB. [S3]' })
    stubBackend(() => json(two))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const msg = await screen.findByTestId('assistant-message')
    expect(within(msg).getAllByTestId('source-item')).toHaveLength(1)
  })

  it.each([
    ['documentation_unavailable', 'Documentation unavailable'],
    ['unable_to_verify', 'Unable to verify'],
    ['out_of_scope', 'Out of scope'],
  ] as const)('shows %s as a labelled note with no sources and no internal ids', async (status, headline) => {
    const r = result({ status, answer: 'Backend explanation text.', sources: [], metadata: { ...result().metadata, grounded: false, card_id: 'M2C-26' } })
    stubBackend(() => json(r))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const note = await screen.findByTestId('status-note')
    expect(note).toHaveTextContent(headline)
    expect(note).toHaveTextContent('Backend explanation text.')
    expect(screen.queryByTestId('source-item')).not.toBeInTheDocument()
    expect(document.body.textContent).not.toMatch(/M2C-\d+/)
  })

  it('shows a topic reference as reference-only, never as a source', async () => {
    const r = result({ status: 'documentation_unavailable', answer: 'Not available.', sources: [], topic_reference: { type: 'topic_reference', title: 'FI-CA Dunning', url: 'https://help.sap.com/docs/d.html', note: 'n' } })
    stubBackend(() => json(r))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const ref = await screen.findByLabelText('Related SAP Help topic')
    expect(ref).toHaveTextContent('Reference only')
    expect(within(ref).getByRole('link')).toHaveAttribute('href', 'https://help.sap.com/docs/d.html')
    expect(screen.queryByRole('region', { name: 'Sources' })).not.toBeInTheDocument()
  })

  it('renders exhausted elaboration as a safe state and hides the unavailable Elaborate action', async () => {
    const safeText = "That's all the additional detail I could verify from the available documentation."
    const exhausted = result({
      status: 'no_additional_verified_evidence',
      answer: safeText,
      sources: [],
      topic_reference: null,
      metadata: {
        ...result().metadata,
        grounded: false,
        can_elaborate: false,
        page_available: true,
        reason_code: 'NO_ADDITIONAL_SUPPORTED_DETAILS',
        follow_up_category: 'elaborate',
      },
    })
    stubBackend(() => json(exhausted))
    render(<App />)
    await userEvent.type(composer(), 'elaborate{Enter}')
    const note = await screen.findByTestId('status-note')
    expect(note).toHaveAttribute('data-status', 'no_additional_verified_evidence')
    expect(note).toHaveTextContent('No more verified detail')
    expect(note).toHaveTextContent(safeText)
    expect(screen.queryByTestId('elaborate-button')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Related SAP Help topic')).not.toBeInTheDocument()
    expect(note.textContent).not.toMatch(/not in the local knowledge base|not currently available/i)
  })

  it('works through Billing → Elaborate → exhausted → repeated typed Elaborate without showing OOS', async () => {
    const safeText = "That's all the additional detail I could verify from the available documentation."
    const billing = result({
      answer: 'Automatic billing calculates charges for a service period. [S1]',
      metadata: { ...result().metadata, card_id: 'M2C-12', card_title: 'Automatic Billing', can_elaborate: true,
        topic_identity: { source_id: 'M2C-12', title: 'Automatic Billing', guide_id: 'billing-guide', page_id: 'billing-page', industry: 'SAP Utilities/IS-U' } },
      sources: [{ ...SOURCE, title: 'Automatic Billing', source_id: 'M2C-12' }],
    })
    const expanded = result({
      answer: 'The billing run uses intervals defined in scheduling. [S1]',
      metadata: { ...billing.metadata, follow_up_category: 'elaborate', can_elaborate: true },
      sources: billing.sources,
    })
    const exhausted = result({
      status: 'no_additional_verified_evidence', answer: safeText, sources: [], topic_reference: null,
      metadata: { ...billing.metadata, grounded: false, can_elaborate: false, reason_code: 'NO_ADDITIONAL_SUPPORTED_DETAILS', follow_up_category: 'elaborate' },
    })
    const replies = [billing, expanded, exhausted, exhausted]
    let call = 0
    const { calls } = stubBackend(() => json(replies[Math.min(call++, replies.length - 1)]))
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(1))
    expect(screen.getByTestId('elaborate-button')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('elaborate-button'))
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(2))
    expect(screen.getAllByTestId('elaborate-button')).toHaveLength(2)
    const expandedMessage = screen.getAllByTestId('assistant-message')[1]
    expect(within(expandedMessage).getByTestId('elaboration-section-title')).toHaveTextContent('Additional detail')
    expect(screen.getAllByTestId('follow-up-questions')).toHaveLength(1)

    await userEvent.click(screen.getAllByTestId('elaborate-button').at(-1)!)
    await waitFor(() => expect(screen.getAllByTestId('status-note')).toHaveLength(1))
    const exhaustedNote = screen.getByTestId('status-note')
    expect(exhaustedNote).toHaveAttribute('data-status', 'no_additional_verified_evidence')
    expect(exhaustedNote).toHaveTextContent(safeText)
    expect(exhaustedNote.className).toContain('bg-accent-soft')
    expect(within(exhaustedNote).getByTestId('exhausted-source')).toHaveTextContent('Automatic Billing')
    expect(within(exhaustedNote).getByRole('link', { name: 'Open source: Automatic Billing' })).toHaveAttribute('href', SOURCE.url!)
    expect(screen.queryByTestId('elaborate-button')).not.toBeInTheDocument()
    // The backend's exhausted state also removes stale Elaborate actions from earlier answers on the same topic.
    expect(screen.queryAllByTestId('elaborate-button')).toHaveLength(0)

    // Even when typed manually after the button disappears, it stays in the safe exhausted state, never OOS.
    await userEvent.type(composer(), 'elaborate{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('status-note')).toHaveLength(2))
    expect(screen.getAllByTestId('status-note')[1]).toHaveAttribute('data-status', 'no_additional_verified_evidence')
    expect(screen.getAllByTestId('status-note')[1]).not.toHaveAttribute('data-status', 'out_of_scope')
    expect(calls.map((request) => request.message)).toEqual([
      'How does billing work?', 'elaborate', 'elaborate', 'elaborate',
    ])
    expect(new Set(calls.map((request) => request.conversation_id)).size).toBe(1)
  })

  it('never uses an exhausted-response source from a different topic', async () => {
    const billingSource = { ...SOURCE, source_id: 'M2C-12', title: 'Billing Guide', url: 'https://help.sap.com/billing' }
    const accountSource = { ...SOURCE, source_id: 'M2C-17', title: 'Contract Account Guide', url: 'https://help.sap.com/contract-accounts' }
    const billing = result({
      answer: 'Billing uses scheduled intervals. [S1]',
      sources: [billingSource],
      metadata: { ...result().metadata, card_id: 'M2C-12', card_title: 'Billing Guide', topic_identity: { source_id: 'M2C-12', title: 'Billing Guide' } },
    })
    const contractAccount = result({
      answer: 'Contract accounts store partner-specific settings. [S1]',
      sources: [accountSource],
      metadata: { ...result().metadata, card_id: 'M2C-17', card_title: 'Contract Account Guide', topic_identity: { source_id: 'M2C-17', title: 'Contract Account Guide' } },
    })
    const exhausted = result({
      status: 'no_additional_verified_evidence',
      answer: "That's all the additional detail I could verify from the available documentation.",
      sources: [billingSource],
      metadata: { ...contractAccount.metadata, grounded: false, can_elaborate: false },
    })
    const replies = [billing, contractAccount, exhausted]
    let index = 0
    stubBackend(() => json(replies[index++]))
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    await screen.findByText(/Billing uses scheduled intervals/)
    await userEvent.type(composer(), 'What is a contract account?{Enter}')
    await screen.findByText(/Contract accounts store partner-specific settings/)
    await userEvent.type(composer(), 'elaborate{Enter}')
    const note = await screen.findByTestId('status-note')

    expect(within(note).getByRole('link', { name: 'Open source: Contract Account Guide' })).toHaveAttribute('href', accountSource.url)
    expect(within(note).queryByRole('link', { name: 'Open source: Billing Guide' })).not.toBeInTheDocument()
  })

  it('labels a successful Elaborate response even when follow-up category metadata is absent', async () => {
    const base = result({ answer: 'Automatic billing uses scheduled intervals. [S1]' })
    const detail = result({
      answer: 'The schedule determines when the billing run executes. [S1]',
      metadata: { ...result().metadata, follow_up_category: null },
      structured_answer: {
        summary: 'The schedule determines when the billing run executes. [S1]',
        sections: [{ title: 'Overview', key: 'overview', content: 'The schedule determines when the billing run executes. [S1]', citations: ['S1'] }],
        citations: ['S1'],
      },
    })
    const replies = [base, detail]
    let index = 0
    stubBackend(() => json(replies[index++]))
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    const baseMessage = await screen.findByTestId('assistant-message')
    await userEvent.click(within(baseMessage).getByTestId('elaborate-button'))
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(2))

    const elaboration = screen.getAllByTestId('assistant-message')[1]
    expect(within(elaboration).getByTestId('elaboration-section-title')).toHaveTextContent('Additional detail')
    expect(within(elaboration).queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
    expect(within(elaboration).queryByTestId('follow-up-questions')).not.toBeInTheDocument()
    expect(screen.getAllByTestId('follow-up-questions')).toHaveLength(1)
  })

  it('hides Elaborate when the backend explicitly reports can_elaborate=false', async () => {
    const noMore = result({ metadata: { ...result().metadata, can_elaborate: false } })
    stubBackend(() => json(noMore))
    render(<App />)
    await userEvent.type(composer(), 'How is billing handled?{Enter}')
    await screen.findByTestId('assistant-message')
    expect(screen.queryByTestId('elaborate-button')).not.toBeInTheDocument()
  })

  it('fails closed when can_elaborate is absent instead of guessing that evidence remains', async () => {
    const withoutAvailability = result({ metadata: { ...result().metadata, can_elaborate: undefined } })
    stubBackend(() => json(withoutAvailability))
    render(<App />)
    await userEvent.type(composer(), 'How does billing work?{Enter}')
    await screen.findByTestId('assistant-message')
    expect(screen.queryByTestId('elaborate-button')).not.toBeInTheDocument()
  })

  it('gives exhausted evidence a distinct visual state from unable-to-verify and unavailable documentation', async () => {
    const replies = [
      result({ status: 'unable_to_verify', answer: 'Not enough evidence.', sources: [], metadata: { ...result().metadata, grounded: false } }),
      result({ status: 'documentation_unavailable', answer: 'This documentation page is unavailable.', sources: [], metadata: { ...result().metadata, grounded: false, page_available: false } }),
      result({ status: 'no_additional_verified_evidence', answer: "That's all the additional detail I could verify from the available documentation.", sources: [], metadata: { ...result().metadata, grounded: false, can_elaborate: false } }),
    ]
    let index = 0
    stubBackend(() => json(replies[Math.min(index++, replies.length - 1)]))
    render(<App />)

    for (const [question, expectedCount] of [['unverified detail', 1], ['missing page', 2], ['elaborate', 3]] as const) {
      await userEvent.type(composer(), `${question}{Enter}`)
      await waitFor(() => expect(screen.getAllByTestId('status-note')).toHaveLength(expectedCount))
    }

    const [unverified, unavailable, exhausted] = screen.getAllByTestId('status-note')
    expect(unverified.className).toContain('bg-rose-50/70')
    expect(unavailable.className).toContain('bg-amber-50/70')
    expect(exhausted.className).toContain('bg-accent-soft')
    expect(exhausted).toHaveTextContent('No more verified detail')
    expect(exhausted.textContent).not.toMatch(/unable to verify|unavailable/i)
  })

  it('keeps Elaborate and related questions scoped to the current topic after a topic switch', async () => {
    const billing = result({
      answer: 'Billing uses scheduled intervals. [S1]',
      metadata: { ...result().metadata, card_id: 'M2C-12', card_title: 'Automatic Billing', topic_identity: { source_id: 'M2C-12', title: 'Automatic Billing' } },
      sources: [{ ...SOURCE, source_id: 'M2C-12', title: 'Automatic Billing' }],
    })
    const contract = result({
      answer: 'A business partner is assigned to a contract account. [S1]',
      metadata: { ...result().metadata, card_id: 'M2C-17', card_title: 'Contract Accounts Overview', topic_identity: { source_id: 'M2C-17', title: 'Contract Accounts Overview' } },
      sources: [{ ...SOURCE, source_id: 'M2C-17', title: 'Contract Accounts Overview' }],
    })
    const contractDetail = result({
      answer: 'A contract account contains settings for its business partner. [S1]',
      metadata: { ...contract.metadata, follow_up_category: 'elaborate' },
      sources: contract.sources,
    })
    const replies = [billing, contract, contractDetail]
    let index = 0
    const { calls } = stubBackend(() => json(replies[index++]))
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(1))
    await userEvent.type(composer(), 'What is a contract account?{Enter}')
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(2))

    const [oldTopicMessage, activeTopicMessage] = screen.getAllByTestId('assistant-message')
    expect(within(oldTopicMessage).queryByTestId('elaborate-button')).not.toBeInTheDocument()
    expect(within(oldTopicMessage).queryByTestId('follow-up-questions')).not.toBeInTheDocument()
    expect(within(activeTopicMessage).getByTestId('elaborate-button')).toBeInTheDocument()
    expect(within(activeTopicMessage).getByTestId('follow-up-questions')).toBeInTheDocument()

    await userEvent.click(within(activeTopicMessage).getByTestId('elaborate-button'))
    await waitFor(() => expect(screen.getAllByTestId('assistant-message')).toHaveLength(3))
    expect(within(screen.getAllByTestId('assistant-message')[2]).getByTestId('elaboration-section-title')).toHaveTextContent('Additional detail')
    expect(calls.map((call) => call.message)).toEqual(['How does billing work?', 'What is a contract account?', 'elaborate'])
  })

  it('only claims a topic page is missing when the backend says it is unavailable', async () => {
    const ref = { type: 'topic_reference' as const, title: 'FI-CA Dunning', url: 'https://help.sap.com/docs/d.html', note: 'n' }
    let n = 0
    stubBackend(() => json(n++ === 0
      ? result({ status: 'unable_to_verify', answer: 'Cannot verify this detail.', sources: [], topic_reference: ref,
          metadata: { ...result().metadata, grounded: false, page_available: true } })
      : result({ status: 'documentation_unavailable', answer: 'The page is unavailable.', sources: [], topic_reference: ref,
          metadata: { ...result().metadata, grounded: false, page_available: false } })))
    render(<App />)
    await userEvent.type(composer(), 'unsupported detail{Enter}')
    const firstRef = await screen.findByLabelText('Related SAP Help topic')
    expect(firstRef).toHaveTextContent('Reference only')
    expect(firstRef).not.toHaveTextContent('not in the local knowledge base')

    await userEvent.type(composer(), 'missing topic{Enter}')
    await waitFor(() => expect(screen.getAllByLabelText('Related SAP Help topic')).toHaveLength(2))
    expect(screen.getAllByLabelText('Related SAP Help topic')[1]).toHaveTextContent('not in the local knowledge base')
  })

  it('copies structured answer text and source cards in their visible citation order', async () => {
    const sourceTwo = { ...SOURCE, marker: 'S2', title: 'Source Two', source_id: 'M2C-22', url: 'https://help.sap.com/two' }
    const sourceFour = { ...SOURCE, marker: 'S4', title: 'Source Four', source_id: 'M2C-24', url: 'https://help.sap.com/four' }
    const structured = result({
      answer: 'Fact from source two [S2].\nFact from source four [S4].',
      sources: [sourceTwo, sourceFour],
      structured_answer: {
        summary: 'Fact from source four [S4].',
        sections: [
          { title: 'First', key: 'first', content: 'Fact from source four [S4].', citations: ['S4'] },
          { title: 'Second', key: 'second', content: 'Fact from source two [S2].', citations: ['S2'] },
        ],
        citations: ['S4', 'S2'],
      },
    })
    stubBackend(() => json(structured))
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Copy answer' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const copied = (writeText.mock.calls[0] as unknown as [string])[0]

    expect(copied).toContain('Fact from source four [1].\nFact from source two [2].')
    expect(copied.indexOf('[1] Source Four')).toBeLessThan(copied.indexOf('[2] Source Two'))
  })

  it('copies the answer together with its sources', async () => {
    stubBackend(() => json(result()))
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    await userEvent.click(await screen.findByRole('button', { name: 'Copy answer' }))
    await waitFor(() => expect(writeText).toHaveBeenCalled())
    const copied = (writeText.mock.calls[0] as unknown as [string])[0]
    expect(copied).toContain('Choose Account > Installment Plan > Create.')
    expect(copied).toContain(SOURCE.url!)
  })
})

describe('untrusted data', () => {
  it('a source whose URL is not http(s) is shown without a link (defence in depth: the backend already drops such URLs)', async () => {
    stubBackend(() => json(result({ sources: [{ ...SOURCE, url: 'javascript:alert(1)' }] })))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const item = await screen.findByTestId('source-item')
    expect(within(item).queryByRole('link')).not.toBeInTheDocument()
    expect(item).toHaveTextContent('No URL available')
  })

  it('answer text containing HTML or links is rendered as inert text', async () => {
    stubBackend(() => json(result({ answer: 'See <a href="https://evil.example">here</a> and [x](https://evil.example). [S1]' })))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const msg = await screen.findByTestId('assistant-message')
    expect(msg.querySelector('.prose-chat a')).toBeNull()
    expect(msg.querySelector('.prose-chat')).toBeInTheDocument()
  })
})

describe('errors', () => {
  it('backend offline: tells the user how to fix it, no generic message', async () => {
    stubBackend(() => { throw new TypeError('Failed to fetch') })
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const err = await screen.findByTestId('error-message')
    expect(err).toHaveTextContent('Unable to reach the RAG service. Make sure the backend is running')
    expect(err.textContent).not.toBe('Something went wrong')
  })

  it('generator failure from the API is explained and no answer is shown', async () => {
    stubBackend(() => json({ error: { code: 'generator_failed', message: 'x' } }, 502))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    const err = await screen.findByTestId('error-message')
    expect(err).toHaveTextContent('answer generator failed')
    expect(err).toHaveTextContent('Ollama')
    expect(screen.queryByTestId('status-note')).not.toBeInTheDocument()
  })

  it('malformed response is reported instead of rendered', async () => {
    stubBackend(() => json({ answer: 42, hello: 'world' }))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    expect(await screen.findByTestId('error-message')).toHaveTextContent('could not understand')
  })

  it('a proxy error page (backend down behind the dev proxy) is reported as unreachable', async () => {
    stubBackend(() => new Response('Bad Gateway', { status: 502 }))
    render(<App />)
    await userEvent.type(composer(), 'q{Enter}')
    expect(await screen.findByTestId('error-message')).toHaveTextContent('Unable to reach the RAG service')
  })

  it('the composer works again after an error', async () => {
    let n = 0
    const { calls } = stubBackend(() => (n++ === 0 ? json({ error: { code: 'pipeline_failed', message: 'x' } }, 500) : json(result())))
    render(<App />)
    await userEvent.type(composer(), 'first{Enter}')
    await screen.findByTestId('error-message')
    await userEvent.type(composer(), 'second{Enter}')
    await waitFor(() => expect(calls).toHaveLength(2))
    await screen.findByText(/Choose Account/)
  })
})

describe('conversations', () => {
  it('creates, lists, switches, starts new and deletes conversations; keeps them in local storage', async () => {
    stubBackend((b) => json(result({ answer: `Answer for ${b.message}. [S1]` })))
    render(<App />)
    await userEvent.type(composer(), 'alpha question{Enter}')
    await screen.findByText(/Answer for alpha question/)
    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    expect(screen.getByRole('heading', { name: 'Ask about SAP Utilities documentation.' })).toBeInTheDocument()
    await userEvent.type(composer(), 'beta question{Enter}')
    await screen.findByText(/Answer for beta question/)
    const nav = screen.getByRole('navigation', { name: 'Chat history' })
    expect(within(nav).getAllByRole('button', { name: /^(alpha|beta) question/ })).toHaveLength(2)
    await userEvent.click(within(nav).getByRole('button', { name: /^alpha question/ }))
    expect(screen.getByText(/Answer for alpha question/)).toBeInTheDocument()
    expect(screen.queryByText(/Answer for beta question/)).not.toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('sapchat.v1.conversations')!)).toHaveLength(2)
    await userEvent.click(screen.getByRole('button', { name: /Delete conversation alpha question/ }))
    expect(within(nav).queryByRole('button', { name: /^alpha question/ })).not.toBeInTheDocument()
  })

  it('restores saved conversations after a reload and the answer survives', async () => {
    stubBackend(() => json(result()))
    const first = render(<App />)
    await userEvent.type(composer(), 'persist me{Enter}')
    await screen.findByText(/Choose Account/)
    first.unmount()
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: /^persist me/ }))
    expect(await screen.findByText(/Choose Account/)).toBeInTheDocument()
    expect(screen.getByTestId('source-item')).toBeInTheDocument()
  })

  it('sends only the selected conversation topic when elaborating after switching chats', async () => {
    const billingIdentity = {
      source_id: 'M2C-12', title: 'Automatic Billing', guide_id: 'billing-guide',
      page_id: 'billing-page', industry: 'SAP Utilities/IS-U',
    }
    const contractIdentity = {
      source_id: 'M2C-17', title: 'Contract Accounts Overview', guide_id: 'contract-guide',
      page_id: 'contract-page', industry: 'SAP Utilities/IS-U',
    }
    const billingSource = { ...SOURCE, title: 'Automatic Billing', source_id: 'M2C-12' }
    const contractSource = { ...SOURCE, title: 'Contract Accounts Overview', source_id: 'M2C-17' }
    const { calls } = stubBackend((body) => {
      if (body.message === 'How does billing work?') {
        return json(result({ answer: 'Billing answer. [S1]', sources: [billingSource],
          metadata: { ...result().metadata, card_id: 'M2C-12', card_title: billingIdentity.title, topic_identity: billingIdentity } }))
      }
      if (body.message === 'What is a contract account?') {
        return json(result({ answer: 'Contract Account answer. [S1]', sources: [contractSource],
          metadata: { ...result().metadata, card_id: 'M2C-17', card_title: contractIdentity.title, topic_identity: contractIdentity } }))
      }
      return json(result({ answer: 'Billing detail. [S2]', sources: [{ ...billingSource, marker: 'S2' }],
        metadata: { ...result().metadata, card_id: 'M2C-12', card_title: billingIdentity.title,
          topic_identity: billingIdentity, follow_up_category: 'elaborate' } }))
    })
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    await screen.findByText(/Billing answer/)
    await userEvent.click(screen.getByRole('button', { name: 'New chat' }))
    await userEvent.type(composer(), 'What is a contract account?{Enter}')
    await screen.findByText(/Contract Account answer/)

    const firstConversationId = calls[0].conversation_id
    const secondConversationId = calls[1].conversation_id
    expect(secondConversationId).not.toBe(firstConversationId)
    const history = screen.getByRole('navigation', { name: 'Chat history' })
    await userEvent.click(within(history).getByRole('button', { name: /^How does billing work/ }))
    const baseMessage = screen.getByTestId('assistant-message')
    await userEvent.click(within(baseMessage).getByTestId('elaborate-button'))
    await waitFor(() => expect(calls).toHaveLength(3))

    expect(calls[2].conversation_id).toBe(firstConversationId)
    expect(calls[2].conversation_id).not.toBe(secondConversationId)
    expect(calls[2].context?.active_topic?.query).toBe('How does billing work?')
    expect(calls[2].context?.active_topic?.identity.source_id).toBe('M2C-12')
    expect(calls[2].context?.active_topic?.identity.source_id).not.toBe('M2C-17')
  })
})

describe('layout and settings', () => {
  it('mobile: the sidebar starts closed, opens as a drawer and closes on selection', async () => {
    mockMatchMedia(false)
    stubBackend(() => json(result()))
    render(<App />)
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'false')
    expect(screen.getByTestId('sidebar')).toHaveClass('hidden')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'true')
    expect(screen.getByTestId('scrim')).toBeInTheDocument()
    await userEvent.click(screen.getByTestId('scrim'))
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'false')
  })

  it('desktop: the sidebar is open and can be collapsed and reopened', async () => {
    mockMatchMedia(true)
    stubBackend(() => json(result()))
    render(<App />)
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'false')
    await userEvent.click(screen.getByRole('button', { name: 'Open sidebar' }))
    expect(screen.getByTestId('sidebar')).toHaveAttribute('data-open', 'true')
  })

  it('traps keyboard focus in settings and restores it to the opener on Escape', async () => {
    stubBackend(() => json(result()))
    render(<App />)
    const trigger = screen.getByRole('button', { name: 'Settings & about' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Settings & about' })
    const closeButton = screen.getByRole('button', { name: 'Close' })
    const lastButton = screen.getByRole('button', { name: 'Delete all conversations' })

    expect(dialog).toHaveFocus()
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
    expect(lastButton).toHaveFocus()
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(closeButton).toHaveFocus()

    closeButton.focus()
    fireEvent.keyDown(window, { key: 'Tab', shiftKey: true })
    expect(lastButton).toHaveFocus()
    fireEvent.keyDown(window, { key: 'Tab' })
    expect(closeButton).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Settings & about' })).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('clear history asks for confirmation and only deletes conversations after approval', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    try {
      stubBackend(() => json(result()))
      render(<App />)
      await userEvent.type(composer(), 'keep this conversation{Enter}')
      await screen.findByText(/Choose Account/)
      await userEvent.click(screen.getByRole('button', { name: 'Settings & about' }))
      const clearButton = screen.getByRole('button', { name: 'Delete all conversations' })

      await userEvent.click(clearButton)
      expect(confirm).toHaveBeenNthCalledWith(1, 'Delete all conversations stored in this browser?')
      expect(screen.getByRole('dialog', { name: 'Settings & about' })).toBeInTheDocument()
      expect(screen.getByText(/Choose Account/)).toBeInTheDocument()

      await userEvent.click(clearButton)
      await waitFor(() => expect(screen.getByRole('heading', { name: 'Ask about SAP Utilities documentation.' })).toBeInTheDocument())
      expect(confirm).toHaveBeenNthCalledWith(2, 'Delete all conversations stored in this browser?')
      await waitFor(() => expect(JSON.parse(localStorage.getItem('sapchat.v1.conversations') ?? 'null')).toEqual([]))
    } finally {
      confirm.mockRestore()
    }
  })

  it('developer details are off by default, can be enabled, and are requested from the backend only then', async () => {
    const withDebug = result({ debug: { routing: { candidates: [{ rank: 1, source_id: 'M2C-24', title: 'T', similarity: 0.5, distance: 0.5 }] }, pipeline: {}, topic: { source_id: 'M2C-24' }, timings_ms: { total_ms: 5 }, citations: { answer_sources: [] } } })
    const { calls } = stubBackend((b) => json(b.debug ? withDebug : result()))
    render(<App />)
    await userEvent.type(composer(), 'one{Enter}')
    await screen.findByText(/Choose Account/)
    expect(calls[0].debug).toBe(false)
    expect(screen.queryByTestId('debug-panel')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Settings & about' }))
    expect(await screen.findByTestId('service-info')).toHaveTextContent('25 of 29')
    await userEvent.click(screen.getByRole('checkbox', { name: /Developer details/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    await userEvent.type(composer(), 'two{Enter}')
    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[1].debug).toBe(true)
    const panel = await screen.findByTestId('debug-panel')
    expect(panel).toHaveTextContent('M2C-24')
    expect(HEALTH.generator).toBe('extractive')
  })
})

describe('App', () => {
  it('clicking Elaborate sends the eligible grounded answer context with the same conversation id', async () => {
    let idCounter = 0
    const spy = vi.spyOn(storage, 'newId').mockImplementation(() => {
      idCounter += 1
      return idCounter === 1 ? 'c1' : `id-${idCounter}`
    })
    const answer = 'Billing is calculated for each service period. [S1]'
    const identity = {
      source_id: 'M2C-12', title: 'Automatic Billing', guide_id: 'billing-guide',
      page_id: 'billing-page', industry: 'SAP Utilities/IS-U',
    }
    const billing = result({
      conversation_id: 'c1', answer,
      sources: [{ ...SOURCE, title: 'Automatic Billing', source_id: 'M2C-12' }],
      metadata: { ...result().metadata, card_id: 'M2C-12', card_title: 'Automatic Billing', topic_identity: identity },
    })
    const detail = result({
      conversation_id: 'c1', answer: 'The billing run follows the configured service-period schedule. [S2]',
      sources: [{ ...SOURCE, marker: 'S2', title: 'Automatic Billing', source_id: 'M2C-12' }],
      metadata: { ...billing.metadata, follow_up_category: 'elaborate' },
    })
    let responseIndex = 0
    try {
      const { calls } = stubBackend(() => json([billing, detail][responseIndex++]))
      render(<App />)
      await userEvent.type(composer(), 'How does billing work?{Enter}')
      await screen.findByText(/Billing is calculated for each service period/)
      const baseMessage = screen.getByTestId('assistant-message')

      expect(calls[0].context).toEqual({ questions: [] })
      await userEvent.click(within(baseMessage).getByTestId('elaborate-button'))
      await waitFor(() => expect(calls).toHaveLength(2))

      expect(calls[1]).toEqual({
        message: 'elaborate',
        conversation_id: 'c1',
        debug: false,
        context: {
          questions: ['How does billing work?'],
          answer,
          active_topic: { query: 'How does billing work?', answer, identity, seen_answers: [] },
        },
      })
    } finally {
      spy.mockRestore()
    }
  })
})
