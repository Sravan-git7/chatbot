import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Citations from '../components/Citations'
import StructuredAnswer from '../components/StructuredAnswer'
import type { Source, StructuredAnswer as StructuredAnswerType } from '../types'

describe('StructuredAnswer and Citations components', () => {
  const sources: Source[] = [
    {
      type: 'page',
      marker: 'S1',
      title: 'Billing Basics',
      section: 'Overview',
      url: 'https://help.sap.com/1',
      source_id: 'M2C-11',
      chunk_id: 'chunk-1',
    },
    {
      type: 'page',
      marker: 'S2',
      title: 'Invoicing Guide',
      section: 'Execution',
      url: 'https://help.sap.com/2',
      source_id: 'M2C-12',
      chunk_id: 'chunk-2',
    },
  ]

  it('renders structured answer sections when valid', () => {
    const structured: StructuredAnswerType = {
      summary: 'Billing is the first step [S1].',
      sections: [
        {
          title: 'Overview',
          key: 'overview',
          lines: ['Billing processes billing orders [S1].'],
          content: 'Billing processes billing orders [S1].',
          citations: ['S1'],
        },
        {
          title: 'Key Details',
          key: 'key_details',
          lines: ['Invoicing creates the final bill [S2].'],
          content: 'Invoicing creates the final bill [S2].',
          citations: ['S2'],
        },
      ],
      citations: ['S1', 'S2'],
    }

    render(
      <StructuredAnswer
        structuredAnswer={structured}
        fallbackAnswer="Fallback raw text"
        sources={sources}
      />,
    )

    expect(screen.getByTestId('structured-answer')).toBeInTheDocument()
    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Key Details')).toBeInTheDocument()
    expect(screen.getByText(/Billing processes billing orders/)).toBeInTheDocument()
    expect(screen.getByText(/Invoicing creates the final bill/)).toBeInTheDocument()
  })

  it('falls back to canonical answer when structured answer is missing or empty', () => {
    render(
      <StructuredAnswer
        structuredAnswer={null}
        fallbackAnswer="Canonical fallback answer [S1]"
        sources={sources}
      />,
    )

    expect(screen.getByTestId('canonical-answer-fallback')).toBeInTheDocument()
    expect(screen.getByText(/Canonical fallback answer/)).toBeInTheDocument()
  })

  it('renders interactive citation chips and triggers onCite', async () => {
    const user = userEvent.setup()
    const onCite = vi.fn()

    render(<Citations citations={['S1', 'S2']} sources={sources} onCite={onCite} />)

    const chip1 = screen.getByTestId('citation-S1')
    expect(chip1).toHaveTextContent('1')
    await user.click(chip1)
    expect(onCite).toHaveBeenCalledWith('S1')
  })
})
