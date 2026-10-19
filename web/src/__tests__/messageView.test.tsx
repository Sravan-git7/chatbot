import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import MessageView from '../components/MessageView'
import type { Message, Source } from '../types'
import { result, SOURCE } from './helpers'

function assistantMessage(overrides: Partial<Message> = {}): Message {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '',
    createdAt: 0,
    result: result(),
    ...overrides,
  }
}

describe('MessageView presentation', () => {
  it('keeps related questions as ordered, responsive, keyboard-operable list items', async () => {
    const user = userEvent.setup()
    const onAskFollowUp = vi.fn()
    const message = assistantMessage()
    render(
      <MessageView
        message={message}
        developerMode={false}
        questionText="How do I create an installment plan?"
        onAskFollowUp={onAskFollowUp}
      />,
    )

    const section = screen.getByTestId('follow-up-questions')
    const list = within(section).getByRole('list')
    const items = within(list).getAllByRole('listitem')
    const buttons = within(list).getAllByRole('button')
    const expectedQuestions = [
      'How are incoming payments analyzed and cleared?',
      'What is an installment plan in Contract Accounts Receivable and Payable?',
    ]

    expect(list).toHaveClass('grid-cols-1', 'sm:grid-cols-2')
    expect(items).toHaveLength(expectedQuestions.length)
    expect(buttons.map((button) => button.textContent)).toEqual(expectedQuestions)
    buttons.forEach((button, index) => {
      expect(button).toHaveAccessibleName(expectedQuestions[index])
      expect(button.parentElement).toBe(items[index])
      expect(button).toHaveClass('w-full', 'whitespace-normal', 'break-words')
    })

    buttons[0].focus()
    await user.keyboard('{Enter}')
    expect(onAskFollowUp).toHaveBeenCalledOnce()
    expect(onAskFollowUp).toHaveBeenLastCalledWith(expectedQuestions[0])

    await user.click(buttons[1])
    expect(onAskFollowUp).toHaveBeenLastCalledWith(expectedQuestions[1])
  })

  it('preserves answer text, source metadata, citations, and source actions while formatting fused labels', async () => {
    const user = userEvent.setup()
    const rawAnswer = 'Utilities Industry (IS-U)Component: one contract account contains all contracts. [S8]'
    const rawSource: Source = {
      ...SOURCE,
      marker: 'S8',
      title: 'Contract Accounts',
      section: 'Contract Accounts > Utilities Industry (IS-U)Component > Overview > Overview',
      source_id: 'M2C-17',
      chunk_id: 'contract-accounts-chunk-8',
      url: 'https://help.sap.com/docs/contract-accounts',
    }
    const unchangedSource = { ...rawSource }
    const message = assistantMessage({ result: result({ answer: rawAnswer, sources: [rawSource] }) })
    render(<MessageView message={message} developerMode={false} />)

    const assistant = screen.getByTestId('assistant-message')
    const prose = assistant.querySelector('.prose-chat')
    expect(prose).toHaveTextContent('Utilities Industry (IS-U) · Component: one contract account contains all contracts.')
    expect(prose).not.toHaveTextContent('Utilities Industry (IS-U)Component')

    const sourceCard = within(assistant).getByTestId('source-item')
    expect(sourceCard).toHaveTextContent('Contract Accounts')
    expect(sourceCard).toHaveTextContent('Utilities Industry (IS-U) · Component > Overview')
    expect(within(sourceCard).getByRole('link', { name: 'Open source: Contract Accounts' }))
      .toHaveAttribute('href', rawSource.url)
    expect(rawSource).toEqual(unchangedSource)

    const citation = within(assistant).getByRole('button', { name: 'Source 1' })
    await user.click(citation)
    expect(sourceCard).toHaveClass('border-accent')
    expect(document.activeElement).toBe(sourceCard)
    expect(document.getElementById('src-assistant-1-S8')).toBeInTheDocument()
    expect(rawSource.marker).toBe('S8')
    expect(rawSource.source_id).toBe('M2C-17')
  })

  it('formats a fused source title without inventing a section or changing its link identity', () => {
    const fusedTitle = 'Utilities Industry (IS-U)Component'
    const source: Source = { ...SOURCE, title: fusedTitle, section: null }
    render(<MessageView message={assistantMessage({ result: result({ answer: 'A verified fact. [S1]', sources: [source] }) })} developerMode={false} />)

    const sourceCard = screen.getByTestId('source-item')
    expect(within(sourceCard).getByText('Utilities Industry (IS-U) · Component')).toBeInTheDocument()
    expect(within(sourceCard).queryByText(fusedTitle)).not.toBeInTheDocument()
    expect(within(sourceCard).getByRole('link', { name: `Open source: ${fusedTitle}` })).toHaveAttribute('href', SOURCE.url)
    expect(source.section).toBeNull()
    expect(source.title).toBe(fusedTitle)
  })

  it('keeps unavailable documentation reference-only and does not show answer sources or suggestions', () => {
    const unavailable = result({
      status: 'documentation_unavailable',
      answer: 'The documentation page is unavailable.',
      sources: [],
      topic_reference: {
        type: 'topic_reference',
        title: 'Contract Accounts Overview',
        url: 'https://help.sap.com/docs/contract-accounts-overview',
        note: 'Reference only.',
      },
      metadata: { ...result().metadata, grounded: false, page_available: false },
    })
    render(<MessageView message={assistantMessage({ result: unavailable })} developerMode={false} />)

    const status = screen.getByTestId('status-note')
    expect(status).toHaveAttribute('data-status', 'documentation_unavailable')
    expect(status).toHaveTextContent('Documentation unavailable')
    expect(screen.queryByRole('region', { name: 'Sources' })).not.toBeInTheDocument()
    expect(screen.queryByTestId('follow-up-questions')).not.toBeInTheDocument()

    const reference = screen.getByLabelText('Related SAP Help topic')
    expect(reference).toHaveTextContent('Reference only')
    expect(within(reference).getByRole('link')).toHaveAttribute('href', 'https://help.sap.com/docs/contract-accounts-overview')
  })

  it('renders honest verification label and badge when verified against documentation', () => {
    const verifiedResult = result({
      status: 'answered',
      answer: 'Contract accounts group contracts. [S1]',
      sources: [SOURCE],
      metadata: {
        ...result().metadata,
        grounded: true,
        verification_status: 'verified',
        verification_label: 'Lexically checked against documentation',
      },
    })
    render(<MessageView message={assistantMessage({ result: verifiedResult })} developerMode={false} />)

    const badge = screen.getByTestId('verification-badge')
    expect(badge).toHaveTextContent('Lexically checked against documentation')
    expect(badge).toHaveClass('text-stone-500')
  })

  it('renders amber warning badge when verification status is partially supported', () => {
    const partialResult = result({
      status: 'answered',
      answer: 'Partial procedural steps. [S1]',
      sources: [SOURCE],
      metadata: {
        ...result().metadata,
        grounded: true,
        verification_status: 'partially_supported',
        verification_label: 'Partially supported by documentation',
      },
    })
    render(<MessageView message={assistantMessage({ result: partialResult })} developerMode={false} />)

    const badge = screen.getByTestId('verification-badge')
    expect(badge).toHaveTextContent('Partially supported by documentation')
    expect(badge).toHaveClass('text-amber-700')
  })

  it('does not display verified badge or phantom sources on insufficient evidence', () => {
    const unableResult = result({
      status: 'unable_to_verify',
      answer: "I couldn't find enough verified information.",
      sources: [],
      metadata: {
        ...result().metadata,
        grounded: false,
        verification_status: 'unverified',
      },
    })
    render(<MessageView message={assistantMessage({ result: unableResult })} developerMode={false} />)

    expect(screen.queryByTestId('verification-badge')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Sources' })).not.toBeInTheDocument()
  })

  it('does not display verification badge when verification_status is unverified even if answered', () => {
    const unverifiedResult = result({
      status: 'answered',
      answer: 'Unverified answer text.',
      sources: [],
      metadata: {
        ...result().metadata,
        grounded: false,
        verification_status: 'unverified',
      },
    })
    render(<MessageView message={assistantMessage({ result: unverifiedResult })} developerMode={false} />)

    expect(screen.queryByTestId('verification-badge')).not.toBeInTheDocument()
  })

  it('renders reference-only card without verification badge or sources on abstention with topic reference', () => {
    const abstentionWithRef = result({
      status: 'unable_to_verify',
      answer: "I couldn't find enough verified information.",
      sources: [],
      topic_reference: {
        type: 'topic_reference',
        title: 'Master Data in SAP Utilities',
        url: 'https://help.sap.com/docs/master-data',
        note: 'Topic reference only - not used as evidence for any answer.',
      },
      metadata: {
        ...result().metadata,
        grounded: false,
        verification_status: 'unverified',
      },
    })
    render(<MessageView message={assistantMessage({ result: abstentionWithRef })} developerMode={false} />)

    expect(screen.queryByTestId('verification-badge')).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Sources' })).not.toBeInTheDocument()
    const ref = screen.getByLabelText('Related SAP Help topic')
    expect(ref).toBeInTheDocument()
    expect(ref).toHaveTextContent('Reference only: this page was not used as evidence for the answer.')
    expect(within(ref).getByRole('link')).toHaveAttribute('href', 'https://help.sap.com/docs/master-data')
  })
})
