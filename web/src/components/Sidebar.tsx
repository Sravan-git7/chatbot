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

function groupConversations(list: Conversation[]): { label: string; items: Conversation[] }[] {
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const startOfYesterday = startOfToday - 86400000

  const today: Conversation[] = []
  const yesterday: Conversation[] = []
  const earlier: Conversation[] = []

  for (const c of list) {
    if (c.updatedAt >= startOfToday) {
      today.push(c)
    } else if (c.updatedAt >= startOfYesterday) {
      yesterday.push(c)
    } else {
      earlier.push(c)
    }
  }

  const groups: { label: string; items: Conversation[] }[] = []
  if (today.length > 0) groups.push({ label: 'Today', items: today })
  if (yesterday.length > 0) groups.push({ label: 'Yesterday', items: yesterday })
  if (earlier.length > 0) groups.push({ label: 'Earlier', items: earlier })
  return groups
}

export default function Sidebar({
  open,
  conversations,
  currentId,
  onNew,
  onSelect,
  onDelete,
  onToggle,
  onAbout,
  mobile,
}: Props) {
  const sorted = [...conversations].sort((a, b) => b.updatedAt - a.updatedAt)
  const groups = groupConversations(sorted)

  return (
    <>
      {mobile && open && (
        <div
          className="fixed inset-0 z-30 bg-stone-900/40 backdrop-blur-xs transition-opacity"
          onClick={onToggle}
          aria-hidden="true"
          data-testid="scrim"
        />
      )}
      <aside
        id="sidebar"
        aria-label="Conversations"
        aria-hidden={!open}
        data-open={open}
        data-testid="sidebar"
        className={`${open ? '' : 'hidden'} ${
          mobile ? 'fixed inset-y-0 left-0 z-40 w-72 shadow-2xl' : 'relative w-[280px] shrink-0'
        } flex flex-col border-r border-stone-200/80 bg-[#f7f6f3] transition-all`}
      >
        {/* Brand Header */}
        <div className="flex items-center justify-between border-b border-stone-200/60 px-3.5 py-3">
          <div className="flex items-center gap-2">
            <div
              className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent text-[11px] font-bold text-white shadow-2xs"
              aria-hidden="true"
            >
              SU
            </div>
            <div className="flex flex-col">
              <span className="text-xs font-semibold tracking-tight text-stone-900">
                SURA
              </span>
              <span className="text-[10px] text-stone-700">
                SAP Utilities Assistant
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={onToggle}
            aria-label="Collapse sidebar"
            className="rounded-lg p-1.5 text-stone-400 hover:bg-stone-200/60 hover:text-stone-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer transition"
          >
            <svg
              width="17"
              height="17"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="3" y="4" width="18" height="16" rx="3" />
              <path d="M9 4v16" />
            </svg>
          </button>
        </div>

        {/* New Chat Action */}
        <div className="p-3">
          <button
            type="button"
            onClick={onNew}
            aria-label="New chat"
            className="group flex w-full items-center justify-between rounded-xl border border-stone-200/90 bg-white px-3 py-2 text-xs font-medium text-stone-800 shadow-2xs transition hover:border-stone-300 hover:bg-stone-50/80 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer"
          >
            <span className="flex items-center gap-2">
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                className="text-stone-500 group-hover:text-stone-700"
                aria-hidden="true"
              >
                <path d="M12 5v14M5 12h14" />
              </svg>
              New chat
            </span>
            <span aria-hidden="true" className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] text-stone-600">
              ⌘K
            </span>
          </button>
        </div>

        {/* Conversation History */}
        <nav
          className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-2"
          aria-label="Chat history"
        >
          {sorted.length === 0 ? (
            <div className="px-3 py-8 text-center">
              <p className="text-xs text-stone-600">
                No recent conversations
              </p>
              <p className="mt-1 text-[11px] text-stone-600">
                Conversations are saved locally in this browser.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {groups.map((group) => (
                <div key={group.label}>
                  <div className="px-2 pb-1.5 pt-1 text-[10px] font-semibold uppercase tracking-wider text-stone-600">
                    {group.label}
                  </div>
                  <ul className="space-y-0.5">
                    {group.items.map((c) => {
                      const isActive = c.id === currentId
                      return (
                        <li key={c.id} className="group relative">
                          <button
                            type="button"
                            onClick={() => onSelect(c.id)}
                            aria-current={isActive ? 'true' : undefined}
                            className={`flex w-full items-center justify-between rounded-lg py-2 pl-2.5 pr-8 text-left text-xs transition cursor-pointer ${
                              isActive
                                ? 'bg-white font-medium text-stone-900 shadow-2xs border border-stone-200/70'
                                : 'text-stone-600 hover:bg-stone-200/60 hover:text-stone-900'
                            }`}
                            title={c.title}
                          >
                            <span className="truncate">{c.title}</span>
                            <span className="shrink-0 pl-1 text-[10px] font-normal text-stone-600">
                              {relativeTime(c.updatedAt)}
                            </span>
                          </button>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              onDelete(c.id)
                            }}
                            aria-label={`Delete conversation ${c.title}`}
                            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-1 text-stone-400 opacity-0 transition hover:bg-stone-200 hover:text-stone-700 focus:opacity-100 group-hover:opacity-100 cursor-pointer"
                          >
                            <svg
                              width="13"
                              height="13"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              aria-hidden="true"
                            >
                              <path d="M6 6l12 12M18 6L6 18" />
                            </svg>
                          </button>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </nav>

        {/* Footer */}
        <div className="border-t border-stone-200/70 p-2.5">
          <button
            type="button"
            onClick={onAbout}
            className="flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left text-xs font-medium text-stone-600 hover:bg-stone-200/60 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent cursor-pointer transition"
          >
            <svg
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className="text-stone-400"
              aria-hidden="true"
            >
              <circle cx="12" cy="12" r="10" />
              <path d="M12 16v-4M12 8h.01" />
            </svg>
            Settings &amp; about
          </button>
        </div>
      </aside>
    </>
  )
}
