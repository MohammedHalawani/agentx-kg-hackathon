import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BrainCircuit, MessageSquare, Plus } from 'lucide-react'
import type { ChatMessage } from '../../hooks/useChatStream'
import type { SampleGroup } from '../../types/contract'
import { cn } from '../../lib/cn'
import { ArtifactCard } from '../artifacts/ArtifactCard'
import { ChatThread } from './ChatThread'
import { Composer } from './Composer'
import { SuggestionPills } from './SuggestionPills'
import { ThreadHistory } from './ThreadHistory'

interface ChatViewProps {
  messages: ChatMessage[]
  busy: boolean
  threadId: string
  send: (text: string) => void
  stop: () => void
  newThread: () => void
  loadThread: (id: string) => void
  groups: SampleGroup[]
  onInspect: (message: ChatMessage) => void
}

// Two states, crossfaded: before the first message the composer sits centered with the heading and
// a few suggestions; once the thread has content it splits into a chat column plus a graph/map/table
// panel (once the thread has produced one). A slim toolbar (history + new chat) sits above both,
// backed by the Neo4j-persisted thread store.
export function ChatView({
  messages,
  busy,
  threadId,
  send,
  stop,
  newThread,
  loadThread,
  groups,
  onInspect,
}: ChatViewProps) {
  const empty = messages.length === 0

  // Every answer that produced a viz is browsable via each message's "View" action; the panel
  // auto-follows the newest one as it arrives, but a manual pick sticks until the next new answer.
  const artifactMessages = useMemo(() => messages.filter((m) => m.artifact?.tool), [messages])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // The interface toggle, visible at every width once the thread has a viz:
  //   Chat  = the conversation alone, full width
  //   Graph = the split view (chat + panel side by side at lg+, panel alone below lg)
  // A new answer with a viz switches to Graph so the result is seen; Chat is one click back.
  const [view, setView] = useState<'chat' | 'graph'>('chat')
  useEffect(() => {
    const latest = artifactMessages[artifactMessages.length - 1]
    if (latest) {
      setSelectedId(latest.id)
      setView('graph')
    }
  }, [artifactMessages.length]) // eslint-disable-line react-hooks/exhaustive-deps
  const activeMessage =
    artifactMessages.find((m) => m.id === selectedId) ?? artifactMessages[artifactMessages.length - 1]

  const selectArtifact = (id: string) => {
    setSelectedId(id)
    setView('graph') // asking to see a message's viz implies the split view
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-4 pt-3">
        {!empty && activeMessage?.artifact && (
          <div className="inline-flex gap-0.5 rounded-lg border border-hairline bg-panel p-0.5">
            {(
              [
                ['chat', 'Chat', MessageSquare],
                ['graph', 'Graph', BrainCircuit],
              ] as const
            ).map(([key, label, Icon]) => (
              <button
                key={key}
                onClick={() => setView(key)}
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                  view === key ? 'bg-surface text-ink shadow-sm' : 'text-muted hover:text-ink',
                )}
              >
                <Icon size={13} />
                {label}
              </button>
            ))}
          </div>
        )}
        <div className="ml-auto flex items-center gap-2">
          <ThreadHistory activeThreadId={threadId} onLoad={loadThread} onNew={newThread} />
          {!empty && (
            <button
              type="button"
              onClick={newThread}
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-hairline bg-panel pl-2.5 pr-3 text-xs font-medium text-muted transition-colors hover:border-accent hover:text-ink"
            >
              <Plus size={15} />
              New chat
            </button>
          )}
        </div>
      </div>
      <AnimatePresence mode="wait" initial={false}>
        {empty ? (
          <motion.div
            key="empty"
            className="relative flex flex-1 flex-col items-center justify-center px-4 pb-16"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, y: -12 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            <div className="relative flex w-full flex-col items-center gap-6">
              <motion.h1
                className="text-center font-display text-3xl font-bold tracking-tight text-ink"
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, ease: 'easeOut' }}
              >
                Ask a question
              </motion.h1>
              <div className="w-full max-w-2xl">
                <Composer onSend={send} busy={busy} autoFocus examples={groups} onStop={stop} />
              </div>
              <div className="w-full max-w-2xl">
                <SuggestionPills groups={groups} onPick={send} />
              </div>
            </div>
          </motion.div>
        ) : (
          <motion.div
            key="active"
            className="flex min-h-0 flex-1"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.25, ease: 'easeOut' }}
          >
            {/* Chat mode: the conversation alone at full width. Graph mode: a fixed-width chat
                column beside the panel at lg+, the panel alone below lg. */}
            <div
              className={cn(
                'min-h-0 flex-col',
                view === 'chat'
                  ? 'flex w-full'
                  : 'hidden lg:flex lg:w-[440px] lg:shrink-0 lg:border-r lg:border-hairline',
              )}
            >
              <ChatThread
                messages={messages}
                onInspect={onInspect}
                activeArtifactId={activeMessage?.id}
                onSelectArtifact={artifactMessages.length > 0 ? selectArtifact : undefined}
              />
              <div className="border-t border-hairline bg-panel px-4 py-3">
                <div className="mx-auto w-full max-w-3xl">
                  <Composer onSend={send} busy={busy} examples={groups} onStop={stop} />
                </div>
              </div>
            </div>

            {/* the graph/map/table panel: wide, full-height, breathing room - not squished under text */}
            {view === 'graph' && activeMessage?.artifact && (
              <div className="min-h-0 flex-1 p-4">
                <ArtifactCard artifact={activeMessage.artifact} />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
