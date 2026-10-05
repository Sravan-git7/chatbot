import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import MessageView from '../components/MessageView'
import type { ChatResult, Message } from '../types'

const answer = 'A contract account is a master data record. [S1]'

function message(sections?: NonNullable<ChatResult['metadata']['elaboration_sections']>): Message {
  const result: ChatResult = {
    schema_version: '11.1',
    conversation_id: 'conversation-1',
    status: 'answered',
    answer,
    sources: [
      {
        type: 'page',
        marker: 'S1',
        title: 'Contract Account',
        section: 'Contract Accounts',
        url: 'https://help.sap.com/example',
        source_id: null,
        chunk_id: null,
      },
    ],
    topic_reference: null,
    metadata: {
      card_id: null,
      card_title: null,
      identity_status: null,
      page_available: true,
      generator: 'extractive',
      grounded: true,
      grounding: { checked: true, ok: true, sentences: 1, violations: 0, cited_markers: ['S1'] },
      pipeline_status: 'answered',
      reason_code: null,
      latency_ms: 1,
      ...(sections ? { elaboration_sections: sections } : {}),
    },
  }
  return { id: 'assistant-1', role: 'assistant', content: answer, createdAt: 1, result }
}

describe('scoped elaboration presentation', () => {
  it('renders static headings only when valid elaboration metadata is present', () => {
    const { rerender } = render(<MessageView message={message()} developerMode={false} />)
    expect(screen.queryByTestId('elaboration-sections')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'What it is / does' })).not.toBeInTheDocument()
    expect(screen.getByText(/A contract account is a master data record/)).toBeInTheDocument()

    rerender(
      <MessageView
        message={message([{ key: 'what_it_is_does', lines: [answer] }])}
        developerMode={false}
      />,
    )
    expect(screen.getByTestId('elaboration-sections')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'What it is / does' })).toBeInTheDocument()
  })

  it('reuses the existing citation chip renderer inside a section', () => {
    render(
      <MessageView
        message={message([{ key: 'what_it_is_does', lines: [answer] }])}
        developerMode={false}
      />,
    )
    expect(screen.getByRole('button', { name: 'Source 1' })).toBeInTheDocument()
  })
})
