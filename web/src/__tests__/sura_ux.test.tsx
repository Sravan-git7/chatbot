import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import App from '../App'
import { json, mockMatchMedia, result, stubBackend } from './helpers'

describe('SURA UX enhancements', () => {
  it('renders SURA assistant introduction, domain suggested questions, and Explore SAP Utilities categories', async () => {
    mockMatchMedia(true)
    const { calls } = stubBackend(() => json(result()))
    render(<App />)

    expect(screen.getByTestId('sura-intro')).toHaveTextContent(/Hi, I'm SURA/i)
    expect(
      screen.getByText(
        /I'm your SAP Utilities documentation assistant\. Ask me about billing, invoicing, contract accounts, business partners/i,
      ),
    ).toBeInTheDocument()

    // Suggested questions required by spec
    for (const q of [
      'How does billing work?',
      'What is a contract account?',
      'What is the invoicing process?',
      'How does a contract account relate to a business partner?',
    ]) {
      expect(screen.getByRole('button', { name: q })).toBeInTheDocument()
    }

    // Explore SAP Utilities section with 5 topic categories
    const explore = screen.getByTestId('explore-topics')
    for (const label of ['Billing', 'Invoicing', 'Contract Accounts', 'Business Partners', 'Receivables']) {
      expect(within(explore).getByRole('tab', { name: label })).toBeInTheDocument()
    }

    // Switching topic tab updates the displayed topic questions and clicking one sends it
    await userEvent.click(within(explore).getByRole('tab', { name: 'Invoicing' }))
    const panel = within(explore).getByTestId('topic-panel')
    const topicQuestionBtn = within(panel).getByRole('button', {
      name: 'How does invoicing create the link to contract accounting?',
    })
    expect(topicQuestionBtn).toBeInTheDocument()

    await userEvent.click(topicQuestionBtn)
    await waitFor(() => expect(calls.length).toBe(1))
    expect(calls[0].message).toBe('How does invoicing create the link to contract accounting?')
  })

  it('cycles through thinking stages while waiting for the backend response', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      mockMatchMedia(true)
      let resolveChat!: (v: Response) => void
      stubBackend(
        () =>
          new Promise<Response>((r) => {
            resolveChat = r
          }),
      )
      render(<App />)

      const input = screen.getByRole('textbox', { name: 'Message' })
      await userEvent.type(input, 'How does billing work?{Enter}')

      const stage = await screen.findByTestId('thinking-stage')
      expect(stage).toHaveTextContent('Searching SAP documentation...')

      act(() => {
        vi.advanceTimersByTime(250)
      })
      expect(screen.getByTestId('thinking-stage')).toHaveTextContent('Finding relevant evidence...')

      act(() => {
        vi.advanceTimersByTime(250)
      })
      expect(screen.getByTestId('thinking-stage')).toHaveTextContent('Verifying sources...')

      act(() => {
        vi.advanceTimersByTime(250)
      })
      expect(screen.getByTestId('thinking-stage')).toHaveTextContent('Preparing answer...')

      await act(async () => {
        resolveChat(json(result()))
      })
      await waitFor(() => expect(screen.queryByTestId('loading')).not.toBeInTheDocument())
    } finally {
      vi.useRealTimers()
    }
  })

  it('shows contextual follow-up questions after a verified answer and sends when clicked', async () => {
    mockMatchMedia(true)
    const { calls } = stubBackend(() => json(result()))
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'How do I create an installment plan?' }))
    const msg = await screen.findByTestId('assistant-message')
    await waitFor(() => expect(within(msg).getByTestId('follow-up-questions')).toBeInTheDocument())

    const followUpBox = within(msg).getByTestId('follow-up-questions')
    expect(followUpBox).toHaveTextContent('You might also want to know')
    const followUpButtons = within(followUpBox).getAllByRole('button')
    expect(followUpButtons.length).toBeGreaterThanOrEqual(2)

    const nextQ = followUpButtons[0].textContent!
    await userEvent.click(followUpButtons[0])
    await waitFor(() => expect(calls.length).toBe(2))
    expect(calls[1].message).toBe(nextQ)
  })

  it('focuses and highlights the matching source card when a citation chip is clicked', async () => {
    mockMatchMedia(true)
    stubBackend(() => json(result()))
    render(<App />)

    await userEvent.click(screen.getByRole('button', { name: 'How does billing work?' }))
    const msg = await screen.findByTestId('assistant-message')
    const citeChips = await within(msg).findAllByRole('button', { name: 'Source 1' })
    expect(citeChips.length).toBeGreaterThanOrEqual(1)

    await userEvent.click(citeChips[0])
    const sourceCard = within(msg).getByTestId('source-item')
    expect(sourceCard.className).toContain('border-accent')
    expect(document.activeElement).toBe(sourceCard)
  })

  it('provides Copy link action on source cards and Retry action on error states', async () => {
    mockMatchMedia(true)
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    let attempt = 0
    stubBackend(() => {
      attempt += 1
      if (attempt === 1) throw new TypeError('Failed to fetch')
      return json(result())
    })
    render(<App />)

    await userEvent.type(screen.getByRole('textbox', { name: 'Message' }), 'How does billing work?{Enter}')
    const err = await screen.findByTestId('error-message')
    const retryBtn = within(err).getByTestId('retry-button')
    expect(retryBtn).toHaveTextContent('Retry')

    await userEvent.click(retryBtn)
    const msg = await screen.findByTestId('assistant-message')
    await waitFor(() => expect(within(msg).queryByTestId('error-message')).not.toBeInTheDocument())
    expect(within(msg).getByTestId('source-item')).toBeInTheDocument()

    const copyLinkBtn = within(msg).getByRole('button', { name: 'Copy source link' })
    await userEvent.click(copyLinkBtn)
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/x/y.html'))
    await waitFor(() => expect(copyLinkBtn).toHaveTextContent('Copied'))
  })

  it.skipIf(process.env.LIVE_BACKEND !== '1')(
    'end-to-end validation against live localhost:8000 backend (welcome, real question, citations, source cards, follow-ups, out-of-scope, sequential questions)',
    async () => {
      mockMatchMedia(true)
      const realFetch = globalThis.fetch
      vi.stubGlobal('fetch', (url: RequestInfo | URL, init?: RequestInit) => {
        const u = String(url)
        const target = u.startsWith('/') ? `http://127.0.0.1:8000${u}` : u
        return realFetch(target, init)
      })

      render(<App />)

      // 1. Verify welcome state + live coverage from /api/health
      expect(screen.getByTestId('sura-intro')).toHaveTextContent(/Hi, I'm SURA/i)
      const coverage = await screen.findByTestId('coverage')
      expect(coverage).toHaveTextContent('Currently 25 of 29 documentation pages are available.')

      // 2. Submit a real question by clicking a suggested question
      await userEvent.click(screen.getByRole('button', { name: 'How do I create an installment plan?' }))
      const msgs1 = await screen.findAllByTestId('assistant-message')
      await waitFor(() => expect(within(msgs1[0]).queryByTestId('loading')).not.toBeInTheDocument(), { timeout: 10000 })

      // 3. Verify final answer, citations, clicking citation, and source cards
      expect(msgs1[0].querySelector('.prose-chat')).toHaveTextContent(/Installment Plan/i)
      const chips = within(msgs1[0]).getAllByRole('button', { name: /^Source \d+$/ })
      expect(chips.length).toBeGreaterThanOrEqual(1)
      await userEvent.click(chips[0])
      const sourceCard = within(msgs1[0]).getByTestId('source-item')
      expect(sourceCard.className).toContain('border-accent')
      expect(within(sourceCard).getByRole('link')).toHaveAttribute(
        'href',
        expect.stringContaining('https://help.sap.com/docs/'),
      )

      // 4. Verify contextual follow-up questions & click one for sequential question
      const followUpSection = within(msgs1[0]).getByTestId('follow-up-questions')
      const followUpBtns = within(followUpSection).getAllByRole('button')
      await userEvent.click(followUpBtns[0])

      await waitFor(
        () => expect(screen.getAllByTestId('assistant-message').length).toBe(2),
        { timeout: 10000 },
      )
      const msgs2 = screen.getAllByTestId('assistant-message')
      await waitFor(() => expect(within(msgs2[1]).queryByTestId('loading')).not.toBeInTheDocument(), { timeout: 10000 })
      expect(msgs2[1].querySelector('.prose-chat')).not.toBeNull()

      // 5. Submit an out-of-scope question sequentially
      const input = screen.getByRole('textbox', { name: 'Message' })
      await userEvent.type(input, 'What is the weather in Hyderabad?{Enter}')
      await waitFor(
        () => expect(screen.getAllByTestId('assistant-message').length).toBe(3),
        { timeout: 10000 },
      )
      const msgs3 = screen.getAllByTestId('assistant-message')
      await waitFor(() => expect(within(msgs3[2]).queryByTestId('loading')).not.toBeInTheDocument(), { timeout: 10000 })
      const oosNote = within(msgs3[2]).getByTestId('status-note')
      expect(oosNote).toHaveAttribute('data-status', 'out_of_scope')
      expect(oosNote).toHaveTextContent('Out of scope')
      expect(oosNote).toHaveTextContent(
        "This question doesn't appear to match the SAP Utilities documentation available to me.",
      )
    },
    20000,
  )
})
