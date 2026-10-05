// Mirrors the backend contract in scripts/rag_service.py / scripts/rag_api.py (schema 11.1). The UI never builds its own answers, sources or URLs.
export type ApiStatus = 'answered' | 'documentation_unavailable' | 'unable_to_verify' | 'out_of_scope'

export interface Source {
  type: 'page'
  marker: string | null
  title: string | null
  section: string | null
  url: string | null
  source_id: string | null
  chunk_id: string | null
}

export interface TopicReference {
  type: 'topic_reference'
  title: string
  url: string
  note: string
}

export interface Grounding {
  checked: boolean
  ok: boolean | null
  sentences: number
  violations: number
  cited_markers: string[]
}

export type ElaborationSectionKey =
  | 'what_it_is_does'
  | 'how_it_works_relationships'
  | 'conditions_prerequisites'
  | 'key_details'

/** Exact answer lines grouped for display; `line_orders` reconstructs their original canonical-answer order. */
export interface ElaborationSection {
  key: ElaborationSectionKey
  lines: string[]
  line_orders?: number[]
}

export interface Metadata {
  card_id: string | null
  card_title: string | null
  identity_status: string | null
  page_available: boolean | null
  generator: string
  grounded: boolean
  grounding: Grounding
  pipeline_status: string
  reason_code: string | null
  latency_ms: number
  /** Present only for an answered scoped extractive elaboration. */
  elaboration_sections?: ElaborationSection[]
}

export interface ChatResult {
  schema_version: string
  conversation_id: string
  status: ApiStatus
  answer: string
  sources: Source[]
  topic_reference: TopicReference | null
  metadata: Metadata
  debug?: Record<string, unknown> | null
}

/** Previous turns sent only to resolve context-dependent follow-up wording. */
export interface ChatContext {
  questions: string[]
  answer?: string
}

export interface Health {
  status: string
  ready: boolean
  generator?: string
  topics?: number
  pages_available?: number
  debug_enabled?: boolean
  reason?: string
}

export type ErrorKind = 'offline' | 'timeout' | 'malformed' | 'http'
export interface ChatError {
  kind: ErrorKind
  code: string
  message: string
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  result?: ChatResult
  error?: ChatError
  pending?: boolean
}

export interface Conversation {
  id: string
  title: string
  createdAt: number
  updatedAt: number
  messages: Message[]
}

export interface Settings {
  developerMode: boolean
}
