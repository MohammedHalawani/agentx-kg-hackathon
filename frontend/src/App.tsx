import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { BrainCircuit } from 'lucide-react'
import { AppNav, type ViewKey } from './components/chat/AppNav'
import { ChatView } from './components/chat/ChatView'
import { InspectModal } from './components/artifacts/InspectModal'
import { DashboardView } from './components/views/DashboardView'
import { FilterView } from './components/views/FilterView'
import { ExploreView } from './components/views/ExploreView'
import { useChatStream } from './hooks/useChatStream'
import type { Artifact, SampleGroup } from './types/contract'

export default function App() {
  const { messages, busy, threadId, send, stop, newThread, loadThread } = useChatStream()
  const [groups, setGroups] = useState<SampleGroup[]>([])
  const [scope, setScope] = useState<string>('')
  const [inspect, setInspect] = useState<Artifact | null>(null)
  const [view, setView] = useState<ViewKey>('chat')
  const [filterFocusId, setFilterFocusId] = useState<string | null>(null)

  useEffect(() => {
    fetch('/samples')
      .then((r) => r.json())
      .then((d: { groups?: SampleGroup[] }) => setGroups(d.groups ?? []))
      .catch(() => undefined)
    fetch('/meta')
      .then((r) => r.json())
      .then((d: { scope?: string }) => setScope(d.scope ?? ''))
      .catch(() => undefined)
  }, [])

  // chat picks a question -> jump to the chat view so the answer is visible
  const ask = (q: string) => {
    setView('chat')
    send(q)
  }

  // Dashboard's "Go pick one →" shortcut tiles jump here with that query's card pre-focused
  const openFilter = (id: string) => {
    setFilterFocusId(id)
    setView('filter')
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-hairline bg-panel px-6 py-3">
        <BrainCircuit className="shrink-0 text-accent" size={20} />
        <h1 className="font-display text-lg font-bold tracking-tight text-ink">Steering-Committee Governance KG</h1>
        {scope && <span className="text-xs text-muted">{scope}</span>}
      </header>

      <div className="flex min-h-0 flex-1">
        <AppNav active={view} onSelect={setView} />
        <main className="min-h-0 flex-1 overflow-hidden">
          <motion.div
            key={view}
            className="h-full"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.2, ease: 'easeOut' }}
          >
            {view === 'chat' && (
              <ChatView
                messages={messages}
                busy={busy}
                threadId={threadId}
                send={ask}
                stop={stop}
                newThread={newThread}
                loadThread={loadThread}
                groups={groups}
                onInspect={(m) => setInspect(m.artifact ?? null)}
              />
            )}
            {view === 'dashboard' && <DashboardView onOpenFilter={openFilter} />}
            {view === 'filter' && <FilterView focusId={filterFocusId} />}
            {view === 'explore' && <ExploreView />}
          </motion.div>
        </main>
      </div>

      <InspectModal
        artifact={inspect}
        open={Boolean(inspect)}
        onOpenChange={(v) => !v && setInspect(null)}
      />
    </div>
  )
}
