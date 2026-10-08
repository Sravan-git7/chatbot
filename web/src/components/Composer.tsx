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

  useEffect(() => {
    ref.current?.focus()
  }, [focusKey])

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
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="mx-auto w-full max-w-3xl px-3 pb-3 sm:px-4 sm:pb-4 xl:max-w-[54rem]"
      aria-label="Ask a question"
    >
      <div className="flex items-end gap-2.5 rounded-3xl border border-stone-300/80 bg-white py-2 pl-4 pr-2 shadow-xs transition focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/15 focus-within:shadow-sm">
        <textarea
          ref={ref}
          value={text}
          rows={1}
          maxLength={MAX_MESSAGE_CHARS}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKey}
          placeholder="Ask SURA about SAP Utilities…"
          aria-label="Message"
          className="max-h-44 min-h-[30px] flex-1 resize-none bg-transparent py-1.5 text-xs sm:text-sm leading-relaxed text-stone-900 outline-none placeholder:text-stone-400"
        />
        <button
          type="submit"
          disabled={!canSend}
          aria-label="Send message"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-accent text-white shadow-2xs transition enabled:hover:bg-accent-dark disabled:cursor-not-allowed disabled:bg-stone-200 disabled:text-stone-400 cursor-pointer"
        >
          <svg
            width="15"
            height="15"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M12 19V5M5 12l7-7 7 7" />
          </svg>
        </button>
      </div>
      <p className="mt-2 px-2 text-center text-[11px] text-stone-600">
        {text.length > MAX_MESSAGE_CHARS - 200 ? `${text.length}/${MAX_MESSAGE_CHARS} characters. ` : ''}
        Answers are grounded in available documentation and answered individually.
      </p>
    </form>
  )
}
