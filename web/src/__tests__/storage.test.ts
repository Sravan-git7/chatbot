import { describe, expect, it } from 'vitest'
import { loadConversations, loadSettings, saveConversations, saveSettings, titleFrom } from '../storage'
import type { Conversation } from '../types'
import { result } from './helpers'

const conv = (over: Partial<Conversation> = {}): Conversation => ({ id: 'a', title: 't', createdAt: 1, updatedAt: 1, messages: [], ...over })

describe('local storage', () => {
  it('round-trips conversations with timestamps and messages', () => {
    const c = conv({ messages: [{ id: 'm', role: 'user', content: 'hi', createdAt: 5 }] })
    saveConversations([c])
    expect(loadConversations()).toEqual([c])
  })
  it('does not persist the debug block', () => {
    saveConversations([conv({ messages: [{ id: 'm', role: 'assistant', content: '', createdAt: 1, result: { ...result(), debug: { big: 'x' } } }] })])
    expect(loadConversations()[0].messages[0].result?.debug).toBeNull()
  })
  it('turns a message that was pending at reload into an explicit interruption error', () => {
    saveConversations([conv({ messages: [{ id: 'm', role: 'assistant', content: '', createdAt: 1, pending: true }] })])
    const m = loadConversations()[0].messages[0]
    expect(m.pending).toBe(false)
    expect(m.error?.code).toBe('interrupted')
  })
  it('survives corrupt storage', () => {
    localStorage.setItem('sapchat.v1.conversations', '{not json')
    expect(loadConversations()).toEqual([])
    localStorage.setItem('sapchat.v1.conversations', '[1,"x",{"id":"ok","messages":[]}]')
    expect(loadConversations().map((c) => c.id)).toEqual(['ok'])
  })
  it('settings default to developer mode off', () => {
    expect(loadSettings()).toEqual({ developerMode: false })
    saveSettings({ developerMode: true })
    expect(loadSettings().developerMode).toBe(true)
  })
  it('titles are trimmed to 48 characters', () => {
    expect(titleFrom('  hello   world ')).toBe('hello world')
    expect(titleFrom('x'.repeat(100))).toHaveLength(48)
    expect(titleFrom('   ')).toBe('New chat')
  })
})
