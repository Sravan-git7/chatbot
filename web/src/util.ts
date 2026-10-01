import type { Source } from './types'

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
