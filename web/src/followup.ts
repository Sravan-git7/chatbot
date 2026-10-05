import type { ChatContext, Conversation } from './types'

/**
 * Conversation context sent with a chat request.
 *
 * It exists for exactly one purpose: a short follow-up such as "elaborate" or "why?" carries no topic of its own, so
 * the backend resolves it against the previous turn before running retrieval. The context is not a source of answers -
 * every answer is still retrieved and verified from the documentation - and it is bounded so the request stays small.
 */
export const MAX_CONTEXT_QUESTIONS = 4
export const MAX_CONTEXT_QUESTION_CHARS = 300
export const MAX_CONTEXT_ANSWER_CHARS = 1200

const clip = (text: string, max: number): string => (text ?? '').replace(/\s+/g, ' ').trim().slice(0, max)

/**
 * The context of the turns *before* `beforeMessageId` (or before the end of the conversation when omitted):
 * the previous questions, most recent first, and the answer paired with the latest assistant turn only when it is a
 * verified answered result. Non-answers and failed turns never lend an older answer to a newer topic.
 * Returns undefined when there is nothing to send, so a first question never carries context.
 */
export function turnContext(conversation: Conversation | null, beforeMessageId?: string): ChatContext | undefined {
  if (!conversation) return undefined
  const found = beforeMessageId ? conversation.messages.findIndex((m) => m.id === beforeMessageId) : conversation.messages.length
  const prior = conversation.messages.slice(0, found < 0 ? conversation.messages.length : found)

  // Only questions no newer than the last assistant turn can describe the answer sent below. If the conversation has
  // an unfinished user turn after it, keep that question but deliberately send no stale answer.
  let lastAssistantIndex = -1
  for (let i = prior.length - 1; i >= 0; i -= 1) {
    if (prior[i].role === 'assistant') {
      lastAssistantIndex = i
      break
    }
  }
  const throughLastAssistant = lastAssistantIndex >= 0 ? prior.slice(0, lastAssistantIndex + 1) : prior
  const lastAssistant = lastAssistantIndex >= 0 ? prior[lastAssistantIndex] : undefined
  const laterUserTurn = lastAssistantIndex >= 0 && prior.slice(lastAssistantIndex + 1).some((m) => m.role === 'user')
  const relevantHistory = laterUserTurn ? prior : throughLastAssistant
  const questions = relevantHistory
    .filter((m) => m.role === 'user')
    .map((m) => clip(m.content, MAX_CONTEXT_QUESTION_CHARS))
    .filter(Boolean)
    .reverse()
    .slice(0, MAX_CONTEXT_QUESTIONS)
  const answer = lastAssistant?.role === 'assistant'
    && !lastAssistant.pending
    && !lastAssistant.error
    && !laterUserTurn
    // Older local conversations predate stored ChatResult status; their completed assistant text remains usable.
    && (!lastAssistant.result || lastAssistant.result.status === 'answered')
    && lastAssistant.content.trim()
    ? clip(lastAssistant.content, MAX_CONTEXT_ANSWER_CHARS)
    : ''
  if (!questions.length && !answer) return undefined
  return answer ? { questions, answer } : { questions }
}
