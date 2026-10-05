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
 * the previous questions, most recent first, and the last completed answer as a fallback anchor.
 * Returns undefined when there is nothing to send, so a first question never carries context.
 */
export function turnContext(conversation: Conversation | null, beforeMessageId?: string): ChatContext | undefined {
  if (!conversation) return undefined
  const found = beforeMessageId ? conversation.messages.findIndex((m) => m.id === beforeMessageId) : conversation.messages.length
  const prior = conversation.messages.slice(0, found < 0 ? conversation.messages.length : found)

  const questions = prior
    .filter((m) => m.role === 'user')
    .map((m) => clip(m.content, MAX_CONTEXT_QUESTION_CHARS))
    .filter(Boolean)
    .reverse()
    .slice(0, MAX_CONTEXT_QUESTIONS)

  const lastAnswer = [...prior].reverse().find((m) => m.role === 'assistant' && !m.pending && !m.error && m.content.trim())
  const answer = lastAnswer ? clip(lastAnswer.content, MAX_CONTEXT_ANSWER_CHARS) : ''
  if (!questions.length && !answer) return undefined
  return answer ? { questions, answer } : { questions }
}
