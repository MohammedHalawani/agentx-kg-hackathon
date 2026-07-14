import { useCallback, useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { History, Trash2 } from 'lucide-react'

interface ThreadSummary {
  id: string
  title: string
  messages: number
}

interface ThreadHistoryProps {
  activeThreadId: string
  onLoad: (id: string) => void
  onNew: () => void
}

// Past conversations, read from Neo4j on open (see backend /threads). Click to reopen, trash to
// delete. Deleting the active thread starts a fresh one so the composer never points at nothing.
export function ThreadHistory({ activeThreadId, onLoad, onNew }: ThreadHistoryProps) {
  const [open, setOpen] = useState(false)
  const [threads, setThreads] = useState<ThreadSummary[]>([])

  const refresh = useCallback(() => {
    fetch('/threads')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { threads?: ThreadSummary[] } | null) => setThreads(d?.threads ?? []))
      .catch(() => setThreads([]))
  }, [])

  const remove = (id: string) => {
    fetch(`/threads/${id}`, { method: 'DELETE' })
      .then(() => {
        if (id === activeThreadId) onNew()
        refresh()
      })
      .catch(() => undefined)
  }

  return (
    <Popover.Root
      open={open}
      onOpenChange={(o) => {
        setOpen(o)
        if (o) refresh()
      }}
    >
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Chat history"
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-hairline bg-panel pl-2.5 pr-3 text-xs font-medium text-muted transition-colors hover:border-accent hover:text-ink data-[state=open]:border-accent data-[state=open]:bg-accent-soft data-[state=open]:text-accent"
        >
          <History size={15} />
          History
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="bottom"
          align="end"
          sideOffset={8}
          className="z-[1200] max-h-[min(60vh,26rem)] w-[min(24rem,88vw)] overflow-y-auto rounded-2xl border border-hairline bg-panel p-2 shadow-2xl"
        >
          <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
            Past conversations
          </div>
          {threads.length === 0 ? (
            <div className="px-3 py-3 text-sm text-muted">No saved conversations yet.</div>
          ) : (
            threads.map((t) => (
              <div
                key={t.id}
                data-active={t.id === activeThreadId}
                className="group flex items-center gap-1 rounded-lg pr-1 transition-colors hover:bg-accent-soft data-[active=true]:bg-accent-soft"
              >
                <button
                  onClick={() => {
                    onLoad(t.id)
                    setOpen(false)
                  }}
                  className="min-w-0 flex-1 px-3 py-2.5 text-left"
                >
                  <div className="truncate text-sm leading-snug text-ink">{t.title}</div>
                  <div className="text-[11px] text-muted">{t.messages} messages</div>
                </button>
                <button
                  onClick={() => remove(t.id)}
                  aria-label={`Delete ${t.title}`}
                  className="shrink-0 rounded-md p-1.5 text-muted opacity-0 transition-opacity hover:text-red-600 group-hover:opacity-100"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
