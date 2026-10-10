import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Citations from '../components/Citations'
import StructuredAnswer, { buildMarkerMap, structuredElaborationAnswer, visibleAnswerText } from '../components/StructuredAnswer'
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

  it('buildMarkerMap assigns contiguous 1-based display numbers to first appearance of markers', () => {
    const map = buildMarkerMap('First fact [S3] and second fact [S1] and repeat [S3] then new [S5].')
    expect(map).toEqual({
      S3: 1,
      S1: 2,
      S5: 3,
    })
  })

  it('the standalone Citations component normalizes non-contiguous backend markers without changing their identity', async () => {
    const onCite = vi.fn()
    render(<Citations citations={['S4', 'S8']} sources={[{ ...sources[0], marker: 'S4' }, { ...sources[1], marker: 'S8' }]} onCite={onCite} />)
    const first = screen.getByRole('button', { name: 'Source 1' })
    expect(screen.getByRole('button', { name: 'Source 2' })).toBeInTheDocument()
    await userEvent.click(first)
    expect(onCite).toHaveBeenCalledWith('S4')
  })

  it('uses the rendered structured-section order for labels and calls elaboration detail by its proper name', () => {
    const sourcesInFallbackOrder: Source[] = [
      { ...sources[0], marker: 'S4' },
      { ...sources[1], marker: 'S2' },
    ]
    const structured: StructuredAnswerType = {
      summary: 'Second content appears first in the fallback [S2].',
      sections: [
        { title: 'Overview', key: 'overview', content: 'First displayed fact [S4].', lines: ['First displayed fact [S4].'], citations: ['S4'] },
        { title: 'Key Details', key: 'key_details', content: 'Second displayed fact [S2].', lines: ['Second displayed fact [S2].'], citations: ['S2'] },
      ],
      citations: ['S2', 'S4'],
    }
    const visible = visibleAnswerText(structured, 'Second content appears first in the fallback [S2]. First [S4].')
    const markerMap = buildMarkerMap(visible, sourcesInFallbackOrder)
    const { container } = render(
      <StructuredAnswer
        structuredAnswer={structured}
        fallbackAnswer="Second content appears first in the fallback [S2]. First [S4]."
        sources={sourcesInFallbackOrder}
        markerMap={markerMap}
        isElaboration
      />,
    )

    expect(markerMap).toEqual({ S4: 1, S2: 2 })
    expect(screen.getByTestId('elaboration-section-title')).toHaveTextContent('Additional detail')
    expect(screen.queryByRole('heading', { name: 'Overview' })).not.toBeInTheDocument()
    const chips = container.querySelectorAll('.cite-chip')
    expect(chips[0]).toHaveTextContent('1')
    expect(chips[1]).toHaveTextContent('2')
  })

  it('uses validated elaboration groups once, without adding a duplicate generic heading', () => {
    const canonical = '1. Release checked bills. [S1]\nThe posting document is recorded. [S2]'
    const sections = [
      { key: 'how_it_works_relationships' as const, lines: ['1. Release checked bills. [S1]'], line_orders: [0] },
      { key: 'key_details' as const, lines: ['The posting document is recorded. [S2]'], line_orders: [1] },
    ]
    const structured = structuredElaborationAnswer(sections, canonical)
    expect(structured?.sections.map((section) => section.title)).toEqual(['How it works', 'Key details'])
    expect(structuredElaborationAnswer([{ ...sections[0], line_orders: [1] }, sections[1]], canonical)).toBeNull()

    const interleavedCanonical = 'A source fact [S1]\nA related fact [S2]\nAnother source fact [S3]'
    const interleaved = structuredElaborationAnswer([
      { key: 'what_it_is_does', lines: ['A source fact [S1]', 'Another source fact [S3]'], line_orders: [0, 2] },
      { key: 'how_it_works_relationships', lines: ['A related fact [S2]'], line_orders: [1] },
    ], interleavedCanonical)
    expect(interleaved && visibleAnswerText(interleaved, interleavedCanonical)).toBe(interleavedCanonical)
    expect(interleaved?.sections.map((section) => section.title)).toEqual(['What it is / does', 'How it works', ''])
    expect(interleaved?.sections[2].showTitle).toBe(false)

    const { container, rerender } = render(
      <StructuredAnswer
        structuredAnswer={structured}
        fallbackAnswer={canonical}
        sources={sources}
        isElaboration
      />,
    )
    expect(screen.getByTestId('elaboration-section-title')).toHaveTextContent('How it works')
    expect(screen.getByRole('heading', { name: 'Key details' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Additional detail' })).not.toBeInTheDocument()

    rerender(
      <StructuredAnswer
        structuredAnswer={interleaved}
        fallbackAnswer={interleavedCanonical}
        sources={sources}
        isElaboration
      />,
    )
    const renderedLines = Array.from(container.querySelectorAll('.text-answer')).map((node) => node.textContent ?? '')
    expect(renderedLines).toHaveLength(3)
    expect(renderedLines[0]).toContain('A source fact')
    expect(renderedLines[1]).toContain('A related fact')
    expect(renderedLines[2]).toContain('Another source fact')
    expect(visibleAnswerText(interleaved, interleavedCanonical)).toBe(interleavedCanonical)
    expect(screen.getAllByRole('heading', { name: 'What it is / does' })).toHaveLength(1)
    expect(screen.queryByRole('heading', { name: 'Additional detail' })).not.toBeInTheDocument()
  })

  it('renders contiguous mapped display numbers and does not render redundant section-header citation clusters', () => {
    const nonContiguousSources: Source[] = [
      {
        type: 'page',
        marker: 'S1',
        title: 'Billing Basics',
        section: 'Overview',
        url: 'https://help.sap.com/1',
        source_id: 'S1-doc',
        chunk_id: 'c-1',
      },
      {
        type: 'page',
        marker: 'S4',
        title: 'Invoicing Guide',
        section: 'Details',
        url: 'https://help.sap.com/4',
        source_id: 'S4-doc',
        chunk_id: 'c-4',
      },
    ]

    const structured: StructuredAnswerType = {
      summary: 'Billing is the first step [S1]. Invoicing follows [S4].',
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
          lines: ['Invoicing creates the final bill [S4].'],
          content: 'Invoicing creates the final bill [S4].',
          citations: ['S4'],
        },
      ],
      citations: ['S1', 'S4'],
    }

    const { container } = render(
      <StructuredAnswer
        structuredAnswer={structured}
        fallbackAnswer="Billing processes billing orders [S1]. Invoicing creates the final bill [S4]."
        sources={nonContiguousSources}
      />,
    )

    // S1 should display as '1' and S4 should display as '2'
    const chips = container.querySelectorAll('.cite-chip')
    expect(chips.length).toBe(2)
    expect(chips[0]).toHaveTextContent('1')
    expect(chips[1]).toHaveTextContent('2')

    // Verify no redundant section-header citation cluster is present inside the section headers
    const sectionHeaders = container.querySelectorAll('section > div:first-child')
    sectionHeaders.forEach((header) => {
      expect(header.querySelector('.cite-chip')).toBeNull()
    })
  })
})
