import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../App'
import { getFollowUpQuestions } from '../util'
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
    expect(calls[1].context).toMatchObject({
      questions: ['What is a contract account?'],
      answer: 'Answer 1 to What is a contract account? [S1]',
      active_topic: {
        query: 'What is a contract account?',
        answer: 'Answer 1 to What is a contract account? [S1]',
        identity: { source_id: 'M2C-24', guide_id: 'guide-plan', page_id: 'page-plan' },
        seen_answers: [],
      },
    })
    expect(screen.getByText('Elaborate.')).toBeInTheDocument()
  })

  it('keeps a recommendation-only Contract Account chip out of Billing follow-up state', async () => {
    const billing = result({
      answer: 'Billing calculates utility charges. Contract Accounts are mentioned in a neighboring section. [S1]',
      sources: [{ ...result().sources[0], title: 'Contract Account reference in billing', section: null, source_id: 'M2C-12' }],
      metadata: {
        ...result().metadata,
        card_id: 'M2C-12', card_title: 'Automatic Billing',
        topic_identity: { source_id: 'M2C-12', title: 'Automatic Billing', guide_id: 'billing-guide', page_id: 'billing-page', industry: 'SAP Utilities/IS-U' },
        follow_up_category: null,
      },
    })
    const elaboration = result({
      answer: 'The billing run selects the consumption items for calculation. [S2]',
      sources: [{ ...result().sources[0], marker: 'S2', source_id: 'M2C-12' }],
      metadata: {
        ...billing.metadata,
        grounding: { checked: true, ok: true, sentences: 1, violations: 0, cited_markers: ['S2'] },
        follow_up_category: 'elaborate',
      },
    })
    const { calls } = stubBackend((body) => json(body.message === 'How does billing work?' ? billing : elaboration))
    render(<App />)

    await userEvent.type(composer(), 'How does billing work?{Enter}')
    const billingMessage = await screen.findByText(/Billing calculates utility charges/)
    expect(billingMessage).toBeInTheDocument()
    expect(getFollowUpQuestions('How does billing work?', billing)).toContain('What is a contract account?')
    expect(await screen.findByRole('button', { name: 'What is a contract account?' })).toBeInTheDocument()

    await userEvent.type(composer(), 'elaborate{Enter}')
    await screen.findByText(/The billing run selects/)
    expect(calls[1].context?.active_topic?.query).toBe('How does billing work?')
    expect(calls[1].context?.active_topic?.identity.source_id).toBe('M2C-12')
    expect(calls[1].context?.questions).toEqual(['How does billing work?'])
    expect(calls[1].context?.questions).not.toContain('What is a contract account?')
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

    expect(calls[2].context?.active_topic).toMatchObject({
      query: topicB,
      answer: `Answer 2 to ${topicB} [S1]`,
      seen_answers: [],
    })

    await userEvent.type(composer(), `${topicA}{Enter}`)
    await screen.findByText(/Answer 4 to What is a contract account/)
    await userEvent.type(composer(), 'Elaborate.{Enter}')
    await screen.findByText(/Answer 5 to Elaborate/)

    expect(calls[4].context?.active_topic).toMatchObject({
      query: topicA,
      answer: `Answer 4 to ${topicA} [S1]`,
      seen_answers: [],
    })
  })
})
