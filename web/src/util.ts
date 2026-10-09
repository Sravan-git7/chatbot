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
    description: 'Billing execution, automatic billing, and budget billing processing',
    questions: [
      'How does automatic billing work?',
      'How are budget billing plans processed?',
    ],
  },
  {
    id: 'invoicing',
    label: 'Invoicing',
    description: 'Invoice creation, posting to contract accounts, and billing links',
    questions: [
      'How does invoicing create the link to contract accounting?',
      'What is the invoicing process?',
    ],
  },
  {
    id: 'contract-accounts',
    label: 'Contract Accounts',
    description: 'Contract account master data, payment terms, and structure',
    questions: [
      'How does a contract account relate to a business partner?',
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
    description: 'Incoming payment processing, clearing, and installment plans',
    questions: [
      'How are incoming payments analyzed and cleared?',
      'What is an installment plan in Contract Accounts Receivable and Payable?',
    ],
  },
]

const FOLLOW_UP_POOLS: { pattern: RegExp; questions: string[] }[] = [
  {
    pattern: /installment|payment|clear|receivable|dunning/i,
    questions: [
      'How do I create an installment plan?',
      'How are incoming payments analyzed and cleared?',
      'What is an installment plan in Contract Accounts Receivable and Payable?',
    ],
  },
  {
    pattern: /invoic/i,
    questions: [
      'How does invoicing create the link to contract accounting?',
      'What is the invoicing process?',
      'How are budget billing plans processed?',
    ],
  },
  {
    pattern: /contract account|business partner|move-in|move-out/i,
    questions: [
      'How does a contract account relate to a business partner?',
      'What is a contract account?',
      'How are incoming payments analyzed and cleared?',
      'How does move-in processing work?',
      'How does move-out processing work?',
    ],
  },
  {
    pattern: /billing|budget/i,
    questions: [
      'How does automatic billing work?',
      'How are budget billing plans processed?',
      'What is the invoicing process?',
    ],
  },
  {
    pattern: /meter|device/i,
    questions: [
      'What does monitoring of meter reading results do?',
      'How are devices managed?',
      'How does billing work?',
    ],
  },
]

function normalizeQuestion(text: string): string {
  return text.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

export function getFollowUpQuestions(question: string, result?: ChatResult): string[] {
  // Related-question chips are only useful below a grounded, current answer. A contextual follow-up (especially an
  // Elaborate response) should not repeat the same recommendation set, and an abstention must not suggest coverage.
  if (
    !result
    || result.status !== 'answered'
    || result.metadata.grounded !== true
    || result.metadata.page_available === false
    || result.metadata.follow_up_category != null
  ) return []

  const currentNorm = normalizeQuestion(question || '')
  const contextText = [
    question || '',
    result.answer || '',
    ...(result.sources?.map((source) => `${source.title ?? ''} ${source.section ?? ''}`) ?? []),
  ].join(' ')

  const candidates = FOLLOW_UP_POOLS
    .filter((pool) => pool.pattern.test(contextText))
    .flatMap((pool) => pool.questions)

  const seen = new Set<string>()
  const out: string[] = []
  for (const candidate of candidates) {
    const key = normalizeQuestion(candidate)
    if (!key || key === currentNorm || seen.has(key)) continue
    seen.add(key)
    out.push(candidate)
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
  sources.forEach((source, index) => {
    // A shared URL/section alone must not make a citation from a different backend source appear under the wrong title.
    const key = [
      source.url ?? `nourl-${index}`,
      source.source_id ?? '',
      source.title ?? '',
      source.section ?? '',
    ].join('\u001f')
    const group = groups.get(key)
    if (group) {
      if (source.marker && !group.markers.includes(source.marker)) group.markers.push(source.marker)
    } else {
      groups.set(key, {
        key,
        markers: source.marker ? [source.marker] : [],
        title: source.title ?? 'SAP Help page',
        section: source.section,
        url: source.url,
      })
    }
  })
  return [...groups.values()]
}

/** Order visual source cards and their labels by the first citation in the displayed answer. */
export function orderSourceGroups(groups: SourceGroup[], displayMap: Record<string, number>): SourceGroup[] {
  const orderOf = (marker: string) => displayMap[marker] ?? Number.POSITIVE_INFINITY
  const firstOrder = (group: SourceGroup) => Math.min(...group.markers.map(orderOf), Number.POSITIVE_INFINITY)
  return groups
    .map((group) => ({ ...group, markers: [...group.markers].sort((left, right) => orderOf(left) - orderOf(right)) }))
    .sort((left, right) => firstOrder(left) - firstOrder(right))
}

/** Remove only obvious repeated page-title/adjacent breadcrumb segments; all backend text remains unchanged. */
export function displayBreadcrumb(section: string | null | undefined, title: string): string | null {
  if (!section?.trim()) return null
  const normalizedTitle = title.trim().replace(/\s+/g, ' ').toLowerCase()
  const parts = section.split(/\s*>\s*/).map((part) => part.trim().replace(/\s+/g, ' ')).filter(Boolean)
  while (parts.length > 0 && parts[0].toLowerCase() === normalizedTitle) parts.shift()
  const cleaned = parts.filter((part, index) => index === 0 || part.toLowerCase() !== parts[index - 1].toLowerCase())
  return cleaned.length ? normalizeDisplayText(cleaned.join(' > ')) : null
}

/** Display-only contiguous citation labels; backend markers and source identities are never changed. */
export function citationDisplayMap(text: string, sources?: Source[]): Record<string, number> {
  const map: Record<string, number> = {}
  const allowed = sources ? new Set(sources.map((source) => source.marker).filter((marker): marker is string => !!marker)) : null
  let count = 1
  const add = (marker: string) => {
    if ((allowed && !allowed.has(marker)) || map[marker] !== undefined) return
    map[marker] = count++
  }
  const regex = /\[(S\d+)\]/g
  let match: RegExpExecArray | null
  while ((match = regex.exec(text)) !== null) add(match[1])
  // A backend source can be valid even if a structured display block omits its marker. Keep it discoverable and
  // contiguous after the markers that are visible in the answer.
  sources?.forEach((source) => { if (source.marker) add(source.marker) })
  return map
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
  if (typeof url !== 'string') return false
  try {
    const parsed = new URL(url)
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && !!parsed.hostname
  } catch {
    return false
  }
}

/**
 * Display-safe normalization for extracted documentation text. Source/evidence stays canonical and backend citation
 * validation operates on canonical spans; this only fixes clear extraction artifacts in display: missing space after a
 * comma, stray spaces before punctuation, and fused labels after a parenthetical code. Citation markers are untouched.
 */
export function normalizeDisplayText(text: string): string {
  return (text ?? '')
    .replace(/,([A-Za-z])/g, ', $1')
    .replace(/\s+([,.!?:;])/g, '$1')
    .replace(/\)([A-Z])/g, ') · $1')
}

/** Plain-text version of the displayed answer and its matching sources for the clipboard. */
export function answerForClipboard(answer: string, sources: Source[], displayMap?: Record<string, number>): string {
  const markerMap = displayMap ?? citationDisplayMap(answer, sources)
  const displayAnswer = normalizeDisplayText(answer).replace(/\[(S\d+)\]/g, (marker, id: string) =>
    markerMap[id] === undefined ? marker : `[${markerMap[id]}]`,
  )
  const groups = orderSourceGroups(groupSources(sources), markerMap)
  if (!groups.length) return displayAnswer
  const lines = groups.map((group) => {
    const markers = group.markers
      .map((marker) => markerMap[marker] === undefined ? `[${marker}]` : `[${markerMap[marker]}]`)
      .join(' ')
    const breadcrumb = displayBreadcrumb(group.section, group.title)
    return `${markers ? `${markers} ` : ''}${normalizeDisplayText(group.title)}${breadcrumb ? ` > ${breadcrumb}` : ''}${group.url ? ` - ${group.url}` : ''}`
  })
  return `${displayAnswer}\n\nSources:\n${lines.join('\n')}`
}

export function relativeTime(ts: number, now = Date.now()): string {
  const s = Math.max(0, Math.round((now - ts) / 1000))
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
