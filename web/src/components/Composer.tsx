import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { MAX_MESSAGE_CHARS } from '../api'

interface Props {
  disabled: boolean
  onSend: (text: string) => void
  focusKey?: string
}

export default function Composer({ disabled, onSend, focusKey }: Props) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)
  const canSend = !disabled && text.trim().length > 0

  useEffect(() => { ref.current?.focus() }, [focusKey])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 176)}px`
  }, [text])

  const submit = () => {
    if (!canSend) return
    onSend(text.trim())
    setText('')
  }
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submit()
    }
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit() }} className="mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4" aria-label="Ask a question">
      <div className="flex items-end gap-2 rounded-3xl border border-stone-300 bg-white py-2 pl-4 pr-2 shadow-sm transition focus-within:border-stone-400 focus-within:shadow-md">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          maxLength={MAX_MESSAGE_CHARS}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask about SAP Utilities…"
          aria-label="Message"
          className="max-h-44 min-h-[28px] flex-1 resize-none bg-transparent py-1.5 text-[16px] leading-6 text-stone-900 outline-none placeholder:text-stone-400"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-white transition enabled:hover:bg-accent-dark disabled:cursor-not-allowed disabled:bg-stone-200 disabled:text-stone-400"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
        </button>
      </div>
      <p className="mt-2 px-2 text-center text-xs text-stone-400">
        {text.length > MAX_MESSAGE_CHARS - 200 ? `${text.length}/${MAX_MESSAGE_CHARS} characters. ` : ''}
        Answers are taken from the available documentation and may be incomplete. Each question is answered on its own.
      </p>
    </form>
  )
}
