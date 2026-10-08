import { describe, expect, it } from 'vitest'
import { EXPLORE_TOPICS, getFollowUpQuestions, normalizeDisplayText } from '../util'
import { result } from './helpers'

describe('conservative display normalization', () => {
  it('fixes the known fused and stray whitespace artifacts without touching citations', () => {
    expect(normalizeDisplayText('In Utilities,one contract account contains all contracts. [S1]'))
      .toBe('In Utilities, one contract account contains all contracts. [S1]')
    expect(normalizeDisplayText('Payments Posted Using Cash App . [S2]'))
      .toBe('Payments Posted Using Cash App. [S2]')
    expect(normalizeDisplayText('Utilities Industry (IS-U)Component [S3]'))
      .toBe('Utilities Industry (IS-U) Component [S3]')
    expect(normalizeDisplayText('A comma, followed by a space, remains unchanged. [S1]'))
      .toBe('A comma, followed by a space, remains unchanged. [S1]')
  })
})

describe('suggested question coverage', () => {
  it('does not suggest navigation questions for any of the four missing corpus topics', () => {
    const questions = [
      ...EXPLORE_TOPICS.flatMap((topic) => topic.questions),
      ...getFollowUpQuestions('How does billing work?', result()),
      ...getFollowUpQuestions('What is a contract account?', result()),
    ].map((question) => question.toLowerCase())

    for (const unavailable of [
      'utilities master data',
      'budget billing plan.',
      'periodic billing and invoicing analysis',
      'contract account business object',
    ]) {
      expect(questions.some((question) => question.includes(unavailable))).toBe(false)
    }
    // The supported M2C-15 topic remains discoverable with its accurate scope.
    expect(questions).toContain('how are budget billing plans processed?')
  })
})
