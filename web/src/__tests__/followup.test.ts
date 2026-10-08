import { describe, expect, it } from 'vitest'
import { getFollowUpQuestions } from '../util'
import { MAX_CONTEXT_ANSWER_CHARS, MAX_CONTEXT_ANSWERS, MAX_CONTEXT_QUESTION_CHARS, turnContext } from '../followup'
import type { ApiStatus, ChatResult, Conversation, Message, TopicIdentity } from '../types'

const BILLING = 'How does billing work?'
const PLAN = 'How do I create an installment plan?'
const CONTRACT = 'What is a contract account?'
const WEATHER = 'What is the weather today?'
const BILLING_ID: TopicIdentity = {
  source_id: 'M2C-12', title: 'Automatic Billing', guide_id: 'guide-billing', page_id: 'page-billing', industry: 'SAP Utilities/IS-U',
}
const PLAN_ID: TopicIdentity = {
  source_id: 'M2C-24', title: 'Creating Installment Plans', guide_id: 'guide-plan', page_id: 'page-plan', industry: 'SAP Utilities/IS-U',
}
const CONTRACT_ID: TopicIdentity = {
  source_id: 'M2C-17', title: 'Contract Accounts Overview', guide_id: 'guide-contract', page_id: 'page-contract', industry: 'SAP Utilities/IS-U',
}

const user = (id: string, content: string): Message => ({ id, role: 'user', content, createdAt: 1 })
function assistant(id: string, content: string, identity: TopicIdentity | undefined, options: {
  status?: ApiStatus
  followUp?: string | null
  grounded?: boolean
} = {}): Message {
  const status = options.status ?? 'answered'
  const source = identity
    ? { type: 'page' as const, marker: 'S1', title: identity.title ?? null, section: null, url: 'https://help.sap.com/page', source_id: identity.source_id, chunk_id: `${identity.guide_id}/${identity.page_id}/001` }
    : null
  const raw = {
    schema_version: '11.1', conversation_id: 'c', status, answer: content,
    sources: source && status === 'answered' ? [source] : [], topic_reference: null,
    metadata: {
      card_id: identity?.source_id ?? null,
      card_title: identity?.title ?? null,
      identity_status: 'resolved_local_page',
      page_available: true,
      generator: 'extractive',
      grounded: options.grounded ?? status === 'answered',
      grounding: { checked: true, ok: status === 'answered', sentences: 1, violations: 0, cited_markers: status === 'answered' ? ['S1'] : [] },
      pipeline_status: status === 'answered' ? 'answered' : status,
      reason_code: null,
      latency_ms: 1,
      topic_identity: identity ?? null,
      follow_up_category: options.followUp ?? null,
    },
  } satisfies ChatResult
  return { id, role: 'assistant', content, createdAt: 1, result: raw }
}

const conversation = (messages: Message[]): Conversation => ({ id: 'c1', title: 'T', createdAt: 1, updatedAt: 1, messages })
const turns = (...pairs: Array<[string, string, TopicIdentity | undefined, { status?: ApiStatus; followUp?: string | null; grounded?: boolean }?]>): Message[] =>
  pairs.flatMap(([question, answer, identity, options], i) => [user(`u${i}`, question), assistant(`a${i}`, answer, identity, options)])

function activeContext(messages: Message[]) {
  return turnContext(conversation(messages))?.active_topic
}

describe('turnContext active-topic state', () => {
  it('sends no context before a successful, grounded topic answer', () => {
    expect(turnContext(null)).toBeUndefined()
    expect(turnContext(conversation([]))).toBeUndefined()
    expect(turnContext(conversation([user('u1', BILLING)]))).toBeUndefined()
    expect(turnContext(conversation([user('u1', BILLING), assistant('a1', 'pending', BILLING_ID, { grounded: false })]))).toBeUndefined()
  })

  it('creates active state only from a successful in-scope standalone query', () => {
    const state = activeContext(turns([BILLING, 'Billing is calculated for the service period. [S1]', BILLING_ID]))!
    expect(state.query).toBe(BILLING)
    expect(state.answer).toBe('Billing is calculated for the service period. [S1]')
    expect(state.identity).toEqual(BILLING_ID)
    expect(state.seen_answers).toEqual([])
    expect(turnContext(conversation(turns([BILLING, 'Billing is calculated for the service period. [S1]', BILLING_ID]))))
      .toMatchObject({ questions: [BILLING], answer: state.answer })
    expect(state.query.length).toBeLessThanOrEqual(MAX_CONTEXT_QUESTION_CHARS)
    expect(state.answer.length).toBeLessThanOrEqual(MAX_CONTEXT_ANSWER_CHARS)
  })

  it('Billing → elaborate → elaborate preserves Billing and tracks shown answers separately', () => {
    const state = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborate', 'Billing detail one. [S2]', BILLING_ID, { followUp: 'elaborate' }],
      ['elaborate', 'Billing detail two. [S3]', BILLING_ID, { followUp: 'elaborate' }],
    ))!
    expect(state.query).toBe(BILLING)
    expect(state.answer).toBe('Billing answer. [S1]')
    expect(state.seen_answers).toEqual(['Billing detail one. [S2]', 'Billing detail two. [S3]'])
  })

  it('Billing → Installment Plan → elaborate → elaborate keeps both elaborations on the latest successful topic', () => {
    const state = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      [PLAN, 'Installment plan answer. [S2]', PLAN_ID],
      ['elaborate', 'Installment plan detail one. [S3]', PLAN_ID, { followUp: 'elaborate' }],
      ['elaborate', 'Installment plan detail two. [S4]', PLAN_ID, { followUp: 'elaborate' }],
    ))!
    expect(state.query).toBe(PLAN)
    expect(state.identity).toEqual(PLAN_ID)
    expect(state.answer).toBe('Installment plan answer. [S2]')
    expect(state.seen_answers).toEqual(['Installment plan detail one. [S3]', 'Installment plan detail two. [S4]'])
  })

  it('Billing → elaborate → Installment Plan → elaborate → elaborate switches once, then remains on Installment Plan', () => {
    const state = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborate', 'Billing detail. [S2]', BILLING_ID, { followUp: 'elaborate' }],
      [PLAN, 'Plan answer. [S3]', PLAN_ID],
      ['elaborate', 'Plan detail one. [S4]', PLAN_ID, { followUp: 'elaborate' }],
      ['elaborate', 'Plan detail two. [S5]', PLAN_ID, { followUp: 'elaborate' }],
    ))!
    expect(state.query).toBe(PLAN)
    expect(state.identity.source_id).toBe(PLAN_ID.source_id)
    expect(state.seen_answers).toEqual(['Plan detail one. [S4]', 'Plan detail two. [S5]'])
  })

  it('a successful Contract Account user query explicitly changes the active topic', () => {
    const state = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborate', 'Billing detail. [S2]', BILLING_ID, { followUp: 'elaborate' }],
      [PLAN, 'Plan answer. [S3]', PLAN_ID],
      ['elaborate', 'Plan detail. [S4]', PLAN_ID, { followUp: 'elaborate' }],
      [CONTRACT, 'Contract Account answer. [S5]', CONTRACT_ID],
      ['elaborate', 'Contract Account detail. [S6]', CONTRACT_ID, { followUp: 'elaborate' }],
    ))!
    expect(state.query).toBe(CONTRACT)
    expect(state.identity).toEqual(CONTRACT_ID)
  })

  it('keeps anaphoric why follow-ups on the active topic for older response metadata', () => {
    const state = activeContext(turns(
      [CONTRACT, 'Contract Account answer. [S1]', CONTRACT_ID],
      ['Explain why companies use it.', 'Contract Account reason detail. [S2]', CONTRACT_ID, { followUp: null }],
    ))!
    expect(state.query).toBe(CONTRACT)
    expect(state.identity).toEqual(CONTRACT_ID)
    expect(state.seen_answers).toEqual(['Contract Account reason detail. [S2]'])
  })

  it('out-of-scope and failed typo turns never replace or clear the last active topic', () => {
    const afterOutOfScope = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborate', 'Billing detail. [S2]', BILLING_ID, { followUp: 'elaborate' }],
      [WEATHER, 'This question is out of scope.', undefined, { status: 'out_of_scope', grounded: false }],
    ))!
    expect(afterOutOfScope.query).toBe(BILLING)

    const afterFailedTypo = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborat', 'Unable to verify.', undefined, { status: 'unable_to_verify', followUp: 'elaborate', grounded: false }],
    ))!
    expect(afterFailedTypo.query).toBe(BILLING)
    expect(afterFailedTypo.seen_answers).toEqual([])

    const unresolvedTypo = activeContext(turns(
      [BILLING, 'Billing answer. [S1]', BILLING_ID],
      ['elaborat', 'Out of scope.', undefined, { status: 'out_of_scope', grounded: false }],
    ))!
    expect(unresolvedTypo.query).toBe(BILLING)
  })

  it('caps accumulated novelty history without replacing the immutable active answer', () => {
    const pairs: Array<[string, string, TopicIdentity | undefined, { followUp?: string | null }?]> = [
      [BILLING, 'Base billing answer.', BILLING_ID],
      ...Array.from({ length: MAX_CONTEXT_ANSWERS + 2 }, (_, i): [string, string, TopicIdentity, { followUp: string }] =>
        ['elaborate', `Billing detail ${i}.`, BILLING_ID, { followUp: 'elaborate' }]),
    ]
    const state = activeContext(turns(...pairs))!
    expect(state.answer).toBe('Base billing answer.')
    expect(state.seen_answers).toHaveLength(MAX_CONTEXT_ANSWERS)
  })

  it('suggested-question generation is presentation-only even when it offers a Contract Account chip', () => {
    const billingAnswer = assistant('a1', 'Billing calculates utility charges. [S1]', BILLING_ID)
    const decorated = {
      ...billingAnswer.result!,
      answer: 'Billing calculates utility charges. Contract Accounts are mentioned in a neighboring section. [S1]',
      sources: [{
        type: 'page' as const, marker: 'S1', title: 'Contract Account reference in billing', section: null,
        url: 'https://help.sap.com/page', source_id: BILLING_ID.source_id, chunk_id: 'billing/001',
      }],
    }
    const message = { ...billingAnswer, content: decorated.answer, result: decorated }
    expect(getFollowUpQuestions(BILLING, decorated)).toContain(CONTRACT)

    // The generated chip is never written into the conversation. The next real user message remains anchored to Billing.
    const state = activeContext([user('u1', BILLING), message, user('u2', 'elaborate')])!
    expect(state.query).toBe(BILLING)
    expect(state.identity).toEqual(BILLING_ID)
  })

  it('keeps only messages before the target user turn when retrying or regenerating', () => {
    const messages = turns(
      [BILLING, 'Billing answer.', BILLING_ID],
      ['elaborate', 'Billing detail.', BILLING_ID, { followUp: 'elaborate' }],
    )
    expect(turnContext(conversation(messages), 'u0')).toBeUndefined()
    expect(turnContext(conversation(messages), 'u1')?.active_topic?.query).toBe(BILLING)
  })

  it('normalizes whitespace and ignores blank turns', () => {
    const state = activeContext([
      user('u1', '  How   does\n billing work? '),
      assistant('a1', 'Billing answer.', BILLING_ID),
      user('u2', '   '),
    ])!
    expect(state.query).toBe('How does billing work?')
  })
})
