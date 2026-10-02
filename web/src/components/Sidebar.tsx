import type { Conversation } from '../types'
import { relativeTime } from '../util'

interface Props {
  open: boolean
  conversations: Conversation[]
  currentId: string | null
  onNew: () => void
  onSelect: (id: string) => void
  onDelete: (id: string) => void
  onToggle: () => void
  onAbout: () => void
  mobile: boolean
}

export default function Sidebar({ open, conversations, currentId, onNew, onSelect, onDelete, onToggle, onAbout, mobile }: Props) {
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)
  return (
    <>
      {mobile && open && <div className="fixed inset-0 z-30 bg-stone-900/30" onClick={onToggle} aria-hidden="true" data-testid="scrim" />}
      <aside
        id="sidebar"
        aria-label="Conversations"
        aria-hidden={!open}
        data-open={open}
        data-testid="sidebar"
        // closed = removed from layout and from the tab order
        className={`${open ? '' : 'hidden'} ${mobile ? 'fixed inset-y-0 left-0 z-40 w-72 shadow-xl' : 'relative w-72 shrink-0'} flex flex-col border-r border-stone-200 bg-[#f4f2ee]`}
      >
        <div className="flex items-center justify-between px-3 py-3">
          <span className="px-1 text-sm font-semibold tracking-tight text-stone-800">SAP Utilities Assistant</span>
          <button type="button" onClick={onToggle} aria-label="Collapse sidebar" className="rounded-lg p-2 text-stone-500 hover:bg-stone-200/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></svg>
          </button>
        </div>
        <div className="px-3 pb-2">
          <button type="button" onClick={onNew} className="flex w-full items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2 text-sm font-medium text-stone-800 shadow-sm transition hover:bg-stone-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
            New chat
          </button>
        </div>
        <nav className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" aria-label="Chat history">
          {sorted.length === 0 ? (
            <p className="px-3 py-4 text-sm text-stone-500">Your conversations are kept in this browser only.</p>
          ) : (
            <ul className="space-y-0.5">
              {sorted.map((c) => (
                <li key={c.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onSelect(c.id)}
                    aria-current={c.id === currentId ? 'true' : undefined}
                    className={`block w-full truncate rounded-lg py-2 pl-3 pr-9 text-left text-sm transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${c.id === currentId ? 'bg-stone-200/80 font-medium text-stone-900' : 'text-stone-700 hover:bg-stone-200/50'}`}
                    title={c.title}
                  >
                    {c.title}
                    <span className="block text-[11px] font-normal text-stone-400">{relativeTime(c.updatedAt)}</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => onDelete(c.id)}
                    aria-label={`Delete conversation ${c.title}`}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1.5 text-stone-400 opacity-0 transition hover:bg-stone-300/60 hover:text-stone-700 focus:opacity-100 group-hover:opacity-100"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>
        <div className="border-t border-stone-200 p-2">
          <button type="button" onClick={onAbout} className="w-full rounded-lg px-3 py-2 text-left text-sm text-stone-700 hover:bg-stone-200/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
            Settings &amp; about
          </button>
        </div>
      </aside>
    </>
  )
}
