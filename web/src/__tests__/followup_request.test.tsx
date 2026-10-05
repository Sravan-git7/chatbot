import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { json, mockMatchMedia, result, stubBackend } from './helpers'

const composer = () => screen.getByRole('textbox', { name: 'Message' })

function numberedAnswers() {
  let n = 0
  return stubBackend((body) => {
    n += 1
    return json(result({ answer: `Answer ${n} to ${body.message} [S1]` }))
  })
}

describe('follow-up request context', () => {
  beforeEach(() => {
    mockMatchMedia(true)
    localStorage.clear()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends no context for the first question and only completed history for a follow-up', async () => {
    const { calls } = numberedAnswers()
    render(<App />)

    await userEvent.type(composer(), 'What is a contract account?{Enter}')
    await screen.findByText(/Answer 1 to What is a contract account/)
    expect(calls[0].context).toBeUndefined()

    await userEvent.type(composer(), 'Elaborate.{Enter}')
    await screen.findByText(/Answer 2 to Elaborate\./)
    expect(calls[1].context).toEqual({
      questions: ['What is a contract account?'],
      answer: 'Answer 1 to What is a contract account? [S1]',
    })
    expect(screen.getByText('Elaborate.')).toBeInTheDocument()
  })

  it('sends the current topic answer after A → B → elaborate and A → B → A → elaborate', async () => {
    const { calls } = numberedAnswers()
    render(<App />)
    const topicA = 'What is a contract account?'
    const topicB = 'How do I create an installment plan?'

    await userEvent.type(composer(), `${topicA}{Enter}`)
    await screen.findByText(/Answer 1 to What is a contract account/)
    await userEvent.type(composer(), `${topicB}{Enter}`)
    await screen.findByText(/Answer 2 to How do I create an installment plan/)
    await userEvent.type(composer(), 'Elaborate.{Enter}')
    await screen.findByText(/Answer 3 to Elaborate/)

    expect(calls[2].context).toEqual({
      questions: [topicB, topicA],
      answer: `Answer 2 to ${topicB} [S1]`,
    })

    await userEvent.type(composer(), `${topicA}{Enter}`)
    await screen.findByText(/Answer 4 to What is a contract account/)
    await userEvent.type(composer(), 'Elaborate.{Enter}')
    await screen.findByText(/Answer 5 to Elaborate/)

    expect(calls[4].context).toEqual({
      questions: [topicA, 'Elaborate.', topicB, topicA],
      answer: `Answer 4 to ${topicA} [S1]`,
    })
  })
})
