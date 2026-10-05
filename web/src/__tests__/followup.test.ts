import { describe, expect, it } from 'vitest'
import { MAX_CONTEXT_ANSWER_CHARS, MAX_CONTEXT_QUESTION_CHARS, MAX_CONTEXT_QUESTIONS, turnContext } from '../followup'
import type { Conversation, Message } from '../types'

const user = (id: string, content: string): Message => ({ id, role: 'user', content, createdAt: 1 })
const answer = (id: string, content: string): Message => ({ id, role: 'assistant', content, createdAt: 1 })

const conversation = (messages: Message[]): Conversation => ({ id: 'c1', title: 'T', createdAt: 1, updatedAt: 1, messages })

describe('turnContext', () => {
  it('sends nothing when there is no previous turn', () => {
    expect(turnContext(null)).toBeUndefined()
    expect(turnContext(conversation([]))).toBeUndefined()
    // a previous question is already a usable anchor (the answer may still be running or may have failed)
    expect(turnContext(conversation([user('u1', 'What is a contract account?')]))).toEqual({ questions: ['What is a contract account?'] })
  })

  it('sends the previous question and the previous answer', () => {
    const c = conversation([user('u1', 'What is a contract account?'), answer('a1', 'A contract account holds master data.')])
    expect(turnContext(c)).toEqual({ questions: ['What is a contract account?'], answer: 'A contract account holds master data.' })
  })

  it('lists the questions most recent first and caps how many are sent', () => {
    const messages = [1, 2, 3, 4, 5, 6].flatMap((n) => [user(`u${n}`, `question ${n}`), answer(`a${n}`, `answer ${n}`)])
    const ctx = turnContext(conversation(messages))!
    expect(ctx.questions).toEqual(['question 6', 'question 5', 'question 4', 'question 3'])
    expect(ctx.questions).toHaveLength(MAX_CONTEXT_QUESTIONS)
    expect(ctx.answer).toBe('answer 6')
  })

  it('keeps the request small: long turns are clipped', () => {
    const c = conversation([
      user('u1', 'q'.repeat(900)), answer('a1', 'First answer.'),
      user('u2', 'next'), answer('a2', 'a'.repeat(5000)),
    ])
    const ctx = turnContext(c)!
    expect(ctx.questions[1]).toHaveLength(MAX_CONTEXT_QUESTION_CHARS)
    expect(ctx.answer).toHaveLength(MAX_CONTEXT_ANSWER_CHARS)
  })

  it('does not pair a completed answer with a newer unanswered question', () => {
    const c = conversation([user('u1', 'Topic A?'), answer('a1', 'Answer for A.'), user('u2', 'Topic B?')])
    expect(turnContext(c)).toEqual({ questions: ['Topic B?', 'Topic A?'] })
  })

  it('pairs topic-switch follow-ups with the latest completed answer', () => {
    const topicA = 'What is a contract account?'
    const topicB = 'How do I create an installment plan?'
    const a = conversation([
      user('u1', topicA), answer('a1', 'Answer for A.'),
      user('u2', topicB), answer('a2', 'Answer for B.'),
    ])
    expect(turnContext(a)).toEqual({ questions: [topicB, topicA], answer: 'Answer for B.' })

    const backToA = conversation([
      ...a.messages,
      user('u3', topicA), answer('a3', 'Answer for A again.'),
    ])
    expect(turnContext(backToA)).toEqual({ questions: [topicA, topicB, topicA], answer: 'Answer for A again.' })
  })

  it('ignores answers that never completed', () => {
    const c = conversation([
      user('u1', 'What is a contract account?'),
      { ...answer('a1', ''), pending: true },
    ])
    expect(turnContext(c)).toEqual({ questions: ['What is a contract account?'] })

    const failed = conversation([
      user('u1', 'What is a contract account?'),
      { ...answer('a1', ''), error: { kind: 'offline', code: 'x', message: 'boom' } },
    ])
    expect(turnContext(failed)).toEqual({ questions: ['What is a contract account?'] })
  })

  it('looks only at the turns before a given turn (retry/regenerate)', () => {
    const c = conversation([
      user('u1', 'What is a contract account?'),
      answer('a1', 'A contract account holds master data.'),
      user('u2', 'elaborate'),
      answer('a2', 'The long answer.'),
    ])
    // regenerating the second turn must not see its own question, its old answer - or anything after it
    expect(turnContext(c, 'u2')).toEqual({ questions: ['What is a contract account?'], answer: 'A contract account holds master data.' })
    // regenerating the first turn has no context at all
    expect(turnContext(c, 'u1')).toBeUndefined()
  })

  it('normalises whitespace and drops blank turns', () => {
    const c = conversation([user('u1', '  What   is\n a contract account? '), user('u2', '   '), answer('a1', 'Because  it  does.')])
    expect(turnContext(c)).toEqual({ questions: ['What is a contract account?'], answer: 'Because it does.' })
  })
})
