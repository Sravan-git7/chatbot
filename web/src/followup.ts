import type { ActiveTopicContext, ChatContext, Conversation, Message, TopicIdentity } from './types'

/**
 * Client-side conversation state for context-dependent follow-ups. Recommendations and source rendering are deliberately
 * absent from this state: only a completed, grounded API answer to a real user message can establish or extend it.
 */
export const MAX_CONTEXT_QUESTIONS = 4
export const MAX_CONTEXT_QUESTION_CHARS = 300
export const MAX_CONTEXT_ANSWER_CHARS = 1200
export const MAX_CONTEXT_ANSWERS = 4

const clip = (text: string, max: number): string => (text ?? '').replace(/\s+/g, ' ').trim().slice(0, max)
const same = (left: string | undefined, right: string | undefined): boolean =>
  !!left && !!right && left.trim().toLocaleLowerCase() === right.trim().toLocaleLowerCase()

/** Bounded fallback for conversations saved before the API exposed `follow_up_category`. */
function looksLikeFollowUp(message: string): boolean {
  const text = clip(message, MAX_CONTEXT_QUESTION_CHARS)
    .toLowerCase()
    .replace(/[’‘]/g, "'")
    .replace(/[.!?,;:]+$/g, '')
    .replace(/^(?:okay|ok|please|and)[,\s]+/, '')
    .trim()
  return /^(?:elaborate|elaborat|elaboratee|elabroate|explain(?: that| this| it)?(?: in (?:more )?detail)?(?: more| further)?|explain why .+\b(?:that|this|it|they|them|those|these)|tell me more|show me more|go into more detail|more details?|in more detail|give me an example|show me an example|example|why(?: is that| does that happen)?|simplify(?: that| this| it)?|in simple terms|what happens (?:next|after that)|what about the next step|continue|go on|how exactly|what does that mean|what about that|what is that)$/.test(text)
}

function identityOf(message: Message): TopicIdentity | undefined {
  const result = message.result
  if (!result) return undefined
  const identity = result.metadata.topic_identity
  if (identity?.source_id) return identity

  // Compatibility for older saved answers. The backend resolves the page identity from this server-known card id.
  const sourceId = result.metadata.card_id
  if (!sourceId) return undefined
  return {
    source_id: sourceId,
    title: result.metadata.card_title ?? undefined,
    industry: 'SAP Utilities/IS-U',
  }
}

function sameTopic(left: TopicIdentity, right: TopicIdentity): boolean {
  return same(left.source_id, right.source_id)
    && (!left.title || !right.title || same(left.title, right.title))
    && (!left.guide_id || !right.guide_id || same(left.guide_id, right.guide_id))
    && (!left.page_id || !right.page_id || same(left.page_id, right.page_id))
    && (!left.industry || !right.industry || same(left.industry, right.industry))
}

function successfulInScope(message: Message): boolean {
  return message.role === 'assistant'
    && !message.pending
    && !message.error
    && message.result?.status === 'answered'
    && message.result.metadata.grounded === true
}

/**
 * Rebuild the active state from the completed user/assistant turns before `beforeMessageId` (or the conversation end).
 *
 * A successful standalone user query replaces the active topic and its base answer. A successful follow-up may add its
 * answer to the separate `seen_answers` list used only to suppress repeated elaboration evidence; it never replaces the
 * active query, original answer, or identity. Failed, pending, out-of-scope, and unverified turns are ignored. Suggested
 * questions do not appear in `Conversation.messages` unless the user actually selects one, so generating/rendering a
 * chip cannot mutate this state.
 */
export function turnContext(conversation: Conversation | null, beforeMessageId?: string): ChatContext | undefined {
  if (!conversation) return undefined
  const found = beforeMessageId ? conversation.messages.findIndex((m) => m.id === beforeMessageId) : conversation.messages.length
  const prior = conversation.messages.slice(0, found < 0 ? conversation.messages.length : found)

  let active: ActiveTopicContext | undefined
  for (let index = 0; index < prior.length; index += 1) {
    const userMessage = prior[index]
    if (userMessage.role !== 'user') continue

    // Appends are user/assistant pairs. If a malformed or unfinished turn intervenes, do not pair it with another query.
    let assistantIndex = index + 1
    while (assistantIndex < prior.length && prior[assistantIndex].role !== 'assistant'
      && prior[assistantIndex].role !== 'user') assistantIndex += 1
    if (assistantIndex >= prior.length || prior[assistantIndex].role !== 'assistant') continue
    const assistant = prior[assistantIndex]
    index = assistantIndex
    if (!successfulInScope(assistant)) continue

    const identity = identityOf(assistant)
    const answer = clip(assistant.content, MAX_CONTEXT_ANSWER_CHARS)
    if (!identity || !answer) continue

    const category = assistant.result?.metadata.follow_up_category
    const isFollowUp = typeof category === 'string' && category.length > 0
      ? true
      : looksLikeFollowUp(userMessage.content)
    if (isFollowUp) {
      // A follow-up is scoped to the topic already active when it was asked. Ignore any inconsistent response identity.
      if (!active || !sameTopic(active.identity, identity)) continue
      const norm = answer.toLowerCase().replace(/\s+/g, ' ').trim()
      const alreadySeen = [active.answer, ...active.seen_answers]
        .some((priorAnswer) => priorAnswer.toLowerCase().replace(/\s+/g, ' ').trim() === norm)
      if (!alreadySeen) {
        active.seen_answers = [...active.seen_answers, answer].slice(-MAX_CONTEXT_ANSWERS)
      }
      continue
    }

    active = {
      query: clip(userMessage.content, MAX_CONTEXT_QUESTION_CHARS),
      answer,
      identity,
      seen_answers: [],
    }
  }

  if (!active) return undefined
  const seenAnswers = active.seen_answers.slice(-MAX_CONTEXT_ANSWERS)
  const latestAnswer = seenAnswers.at(-1) ?? active.answer
  return {
    // Keep the legacy fields, but expose only the authoritative active topic—not raw history or recommendation text.
    questions: [active.query],
    answer: latestAnswer,
    active_topic: { ...active, seen_answers: seenAnswers },
  }
}
