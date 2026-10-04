import type { ChatResult, Source } from './types'

export interface TopicCategory {
  id: string
  label: string
  description: string
  questions: string[]
}

export const EXPLORE_TOPICS: TopicCategory[] = [
  {
    id: 'billing',
    label: 'Billing',
    description: 'Billing execution, automatic billing, and budget billing plans',
    questions: [
      'How is billing handled?',
      'How does automatic billing work?',
      'How does a budget billing plan work?',
    ],
  },
  {
    id: 'invoicing',
    label: 'Invoicing',
    description: 'Invoice creation, posting to contract accounts, and billing links',
    questions: [
      'How does invoicing create the link to contract accounting?',
      'How are invoices reversed?',
    ],
  },
  {
    id: 'contract-accounts',
    label: 'Contract Accounts',
    description: 'Contract account master data, payment terms, and structure',
    questions: [
      'What is the contract account business object?',
      'How are incoming payments analyzed and cleared?',
    ],
  },
  {
    id: 'business-partners',
    label: 'Business Partners',
    description: 'Customer relationships, move-in, and move-out processing',
    questions: [
      'How does move-in processing work?',
      'How does move-out processing work?',
    ],
  },
  {
    id: 'receivables',
    label: 'Receivables',
    description: 'Installment plans, payment clearing, and meter reading monitoring',
    questions: [
      'What happens when an installment plan is deactivated?',
      'What does monitoring of meter reading results do?',
    ],
  },
]

const FOLLOW_UP_POOLS: { pattern: RegExp; questions: string[] }[] = [
  {
    pattern: /installment|payment|clear|receivable|dunning/i,
    questions: [
      'How are incoming payments analyzed and cleared?',
      'How do I create an installment plan?',
      'How does invoicing create the link to contract accounting?',
      'What is a contract account?',
    ],
  },
  {
    pattern: /invoic/i,
    questions: [
      'How does invoicing create the link to contract accounting?',
      'What is the invoicing process?',
      'How does billing work?',
      'What is a contract account?',
    ],
  },
  {
    pattern: /contract account|business partner|move-in|move-out/i,
    questions: [
      'How does a contract account relate to a business partner?',
      'What is a contract account?',
      'What is the invoicing process?',
      'How does move-in processing work?',
    ],
  },
  {
    pattern: /billing|budget|meter|device|rate/i,
    questions: [
      'How does billing work?',
      'What is the invoicing process?',
      'What does monitoring of meter reading results do?',
      'How are devices managed?',
    ],
  },
]

const DEFAULT_FOLLOW_UPS = [
  'How does billing work?',
  'What is a contract account?',
  'What is the invoicing process?',
  'How does a contract account relate to a business partner?',
]

export function getFollowUpQuestions(question: string, result?: ChatResult): string[] {
  const norm = (s: string) => s.trim().toLowerCase().replace(/[?.!]+$/, '')
  const currentNorm = norm(question || '')
  const contextText = [
    question || '',
    result?.answer || '',
    ...(result?.sources?.map((s) => `${s.title ?? ''} ${s.section ?? ''}`) ?? []),
  ].join(' ')

  const candidates: string[] = []
  for (const pool of FOLLOW_UP_POOLS) {
    if (pool.pattern.test(contextText)) {
      candidates.push(...pool.questions)
    }
  }
  candidates.push(...DEFAULT_FOLLOW_UPS)

  const seen = new Set<string>()
  const out: string[] = []
  for (const q of candidates) {
    const key = norm(q)
    if (!key || key === currentNorm || seen.has(key)) continue
    seen.add(key)
    out.push(q)
    if (out.length === 3) break
  }
  return out
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fall through to the legacy path */
  }
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

export interface SourceGroup {
  key: string
  markers: string[]
  title: string
  section: string | null
  url: string | null
}

/** Chunks of the same page section are listed once with all their markers. Only data from the backend is used; nothing is constructed. */
export function groupSources(sources: Source[]): SourceGroup[] {
  const groups = new Map<string, SourceGroup>()
  sources.forEach((s, i) => {
    const key = `${s.url ?? `nourl-${i}`}|${s.section ?? ''}`
    const g = groups.get(key)
    if (g) {
      if (s.marker) g.markers.push(s.marker)
    } else {
      groups.set(key, { key, markers: s.marker ? [s.marker] : [], title: s.title ?? 'SAP Help page', section: s.section, url: s.url })
    }
  })
  return [...groups.values()]
}

export function displayUrl(url: string): string {
  try {
    const u = new URL(url)
    return `${u.host}${u.pathname}`
  } catch {
    return url
  }
}

export function isHttpUrl(url: string | null | undefined): url is string {
  return typeof url === 'string' && /^https?:\/\//i.test(url)
}

/** Plain-text version of an answer for the clipboard: the answer as written, followed by its sources. */
export function answerForClipboard(answer: string, sources: Source[]): string {
  const groups = groupSources(sources)
  if (!groups.length) return answer
  const lines = groups.map((g) => `${g.markers.map((m) => `[${m}]`).join('')} ${g.title}${g.section && g.section !== g.title ? ` > ${g.section}` : ''}${g.url ? ` - ${g.url}` : ''}`)
  return `${answer}\n\nSources:\n${lines.join('\n')}`
}

export function relativeTime(ts: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ts) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
