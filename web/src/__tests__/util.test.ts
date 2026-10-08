import { describe, expect, it } from 'vitest'
import {
  answerForClipboard,
  citationDisplayMap,
  displayBreadcrumb,
  EXPLORE_TOPICS,
  getFollowUpQuestions,
  groupSources,
  isHttpUrl,
  normalizeDisplayText,
  orderSourceGroups,
} from '../util'
import { EXAMPLE_PROMPTS } from '../components/Welcome'
import type { Source } from '../types'
import { result, SOURCE } from './helpers'

describe('safe source URLs', () => {
  it('accepts only absolute HTTP(S) links with a host', () => {
    expect(isHttpUrl('https://help.sap.com/docs/page')).toBe(true)
    expect(isHttpUrl('http://help.sap.com/page')).toBe(true)
    expect(isHttpUrl('https://')).toBe(false)
    expect(isHttpUrl('javascript:alert(1)')).toBe(false)
    expect(isHttpUrl('')).toBe(false)
    expect(isHttpUrl(null)).toBe(false)
  })
})

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
  it('keeps the small landing set and topic chips within verified, available documentation topics', () => {
    expect(EXAMPLE_PROMPTS).toEqual([
      'How does billing work?',
      'What is a contract account?',
      'What is the invoicing process?',
      'How does a contract account relate to a business partner?',
      'How do I create an installment plan?',
      'How are devices managed?',
    ])
    const questions = [
      ...EXAMPLE_PROMPTS,
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
    // The supported processing topic is not the unavailable Budget Billing Plan master-data page.
    expect(questions).toContain('how are budget billing plans processed?')
    expect(questions).toContain('how does move-in processing work?')
    expect(questions).toContain('how does move-out processing work?')
  })

  it('does not repeat the current question and omits related chips for follow-ups, abstentions, or missing pages', () => {
    const suggestions = getFollowUpQuestions('HOW DOES AUTOMATIC BILLING WORK!', result({
      answer: 'Automatic billing uses scheduled intervals. [S1]',
      sources: [{ ...SOURCE, title: 'Automatic Billing', source_id: 'M2C-12' }],
    }))
    expect(suggestions).not.toContain('How does automatic billing work?')
    expect(new Set(suggestions.map((question) => question.toLowerCase())).size).toBe(suggestions.length)

    expect(getFollowUpQuestions('elaborate', result({ metadata: { ...result().metadata, follow_up_category: 'elaborate' } }))).toEqual([])
    expect(getFollowUpQuestions('question', result({ status: 'unable_to_verify', metadata: { ...result().metadata, grounded: false } }))).toEqual([])
    expect(getFollowUpQuestions('question', result({ metadata: { ...result().metadata, page_available: false } }))).toEqual([])
  })
})

describe('citation labels and source identity', () => {
  const first: Source = { ...SOURCE, marker: 'S8', source_id: 'M2C-11', title: 'Billing Guide', section: 'Billing Guide > Billing Guide > Overview' }
  const second: Source = { ...SOURCE, marker: 'S3', source_id: 'M2C-12', title: 'Automatic Billing', section: 'Automatic Billing > Scheduling' }

  it('assigns contiguous labels in displayed citation order without changing backend markers', () => {
    const sources = [first, second]
    expect(citationDisplayMap('First fact [S8]. Second fact [S3].', sources)).toEqual({ S8: 1, S3: 2 })
    expect(sources.map((source) => source.marker)).toEqual(['S8', 'S3'])
  })

  it('orders source cards and markers by the visible answer citation order', () => {
    const displayMap = citationDisplayMap('First fact [S8]. Second fact [S3].', [second, first])
    const ordered = orderSourceGroups(groupSources([second, first]), displayMap)
    expect(ordered.map((group) => group.title)).toEqual(['Billing Guide', 'Automatic Billing'])
    expect(ordered.map((group) => group.markers)).toEqual([['S8'], ['S3']])
  })

  it('does not merge different backend source identities that share a URL and breadcrumb', () => {
    const sameLocation = [
      { ...first, title: 'Billing Guide', section: 'Overview' },
      { ...first, marker: 'S9', source_id: 'M2C-12', title: 'Automatic Billing', section: 'Overview' },
    ]
    expect(groupSources(sameLocation)).toHaveLength(2)
  })

  it('cleans repeated breadcrumb artifacts and copies human-facing contiguous citation numbers', () => {
    expect(displayBreadcrumb('Billing Guide > Billing Guide > Overview > Overview', 'Billing Guide')).toBe('Overview')
    const copied = answerForClipboard('First fact [S8]. Second fact [S3].', [first, second])
    expect(copied).toContain('First fact [1]. Second fact [2].')
    expect(copied).toContain('[1] Billing Guide > Overview - https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/x/y.html')
    expect(copied).toContain('[2] Automatic Billing > Scheduling - https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/x/y.html')
    expect(copied).not.toContain('[S8]')
    expect(copied).not.toContain('[S3]')
  })
})
