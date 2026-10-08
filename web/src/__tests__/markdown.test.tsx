import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Markdown, { prepare } from '../components/Markdown'

const markers = new Set(['S1'])

describe('markdown safety', () => {
  it('does not render raw HTML, scripts, iframes or event handlers', () => {
    const { container } = render(<Markdown text={'<script>window.__x=1</script><img src=x onerror="window.__x=2"><iframe src="https://evil.example"></iframe>\n\n**bold** [S1]'} markers={markers} />)
    expect(container.querySelector('script, iframe, img')).toBeNull()
    expect(container.innerHTML).not.toContain('onerror')
    expect((window as unknown as { __x?: number }).__x).toBeUndefined()
    expect(container.querySelector('strong')).toHaveTextContent('bold')
  })

  it('never renders links from the text: javascript:, https and relative links become plain text', () => {
    const { container } = render(<Markdown text={'[click](javascript:alert(1)) [ok](https://evil.example/x) [rel](/admin) <https://auto.example>'} markers={markers} />)
    expect(container.querySelector('a')).toBeNull()
    expect(container.textContent).toContain('click')
  })

  it('images in markdown are dropped', () => {
    const { container } = render(<Markdown text={'![pixel](https://evil.example/p.gif)'} markers={markers} />)
    expect(container.querySelector('img')).toBeNull()
  })

  it('only known markers become citation chips; an unknown marker is shown as text', () => {
    render(<Markdown text={'Known. [S1] Unknown. [S9]'} markers={markers} />)
    expect(screen.getAllByRole('button', { name: 'Source 1' })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: 'Source 9' })).toBeNull()
    expect(screen.getByText('[S9]')).toBeInTheDocument()
  })

  it('an injected citation-style link cannot point anywhere but a known marker', () => {
    const { container } = render(<Markdown text={'[S1](https://evil.example) [x](#cite-S7)'} markers={markers} />)
    expect(container.querySelector('a')).toBeNull()
  })

  it('renders lists, tables and code blocks, and code blocks have a copy button', () => {
    const md = '- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\nEA10 --run\n```'
    const { container } = render(<Markdown text={md} markers={markers} />)
    expect(container.querySelectorAll('li')).toHaveLength(2)
    expect(container.querySelector('table')).not.toBeNull()
    expect(container.querySelector('pre')).toHaveTextContent('EA10 --run')
    expect(screen.getByRole('button', { name: 'Copy code' })).toBeInTheDocument()
  })

  it('prepare() turns extractive one-sentence-per-line output into paragraphs and markers into cite links', () => {
    expect(prepare('A. [S1]\nB. [S2]')).toBe('A. [S1](#cite-S1)\n\nB. [S2](#cite-S2)')
  })

  it('collapses redundant adjacent visual citations while keeping distinct sources clickable', () => {
    const prepared = prepare('First fact. [S1]\nSecond fact. [S1]\nThird fact. [S2]')
    expect(prepared.match(/\(#cite-S1\)/g)).toHaveLength(1)
    expect(prepared).toContain('Third fact. [S2](#cite-S2)')
    render(<Markdown text={'First fact. [S1]\nSecond fact. [S1]\nThird fact. [S2]'} markers={new Set(['S1', 'S2'])} />)
    expect(screen.getAllByRole('button', { name: 'Source 1' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Source 2' })).toHaveLength(1)
  })
})
