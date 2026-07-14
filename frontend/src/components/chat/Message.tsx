import { useEffect, useRef, useState } from 'react'
import { motion } from 'motion/react'
import { BrainCircuit, Check, Copy, Map as MapIcon, ScanSearch } from 'lucide-react'
import type { ChatMessage } from '../../hooks/useChatStream'
import { useSmoothText } from '../../hooks/useSmoothText'
import { cn } from '../../lib/cn'
import { Markdown } from './Markdown'
import { MapModal } from '../artifacts/MapModal'
import { ReasoningTrace } from './ReasoningTrace'
import { TrustChip } from './TrustChip'

interface MessageProps {
  message: ChatMessage
  onInspect: () => void
  // wiring for the side graph/map panel (ChatView owns "which message's artifact is shown")
  isActiveArtifact?: boolean
  onSelectArtifact?: () => void
}

export function Message({ message, onInspect, isActiveArtifact, onSelectArtifact }: MessageProps) {
  const [copied, setCopied] = useState(false)
  const [mapOpen, setMapOpen] = useState(false)
  const copiedTimer = useRef<ReturnType<typeof setTimeout>>(undefined)
  useEffect(() => () => clearTimeout(copiedTimer.current), [])

  // reveal the answer at a steady pace rather than in SSE bursts; hold the action bar and the
  // artifact until the text has finished typing out, so they land together with the last word
  const { text: shownContent, revealing } = useSmoothText(message.content)

  if (message.role === 'user') {
    return (
      <motion.div
        className="flex justify-end"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl bg-accent px-4 py-2.5 text-sm leading-relaxed text-white">
          {message.content}
        </div>
      </motion.div>
    )
  }

  const copy = () => {
    void navigator.clipboard?.writeText(message.content).then(() => {
      setCopied(true)
      clearTimeout(copiedTimer.current)
      copiedTimer.current = setTimeout(() => setCopied(false), 1200)
    })
  }

  const producing = Boolean(message.streaming) || revealing
  const showActions = !producing && Boolean(message.content)
  const confidence = message.artifact?.confidence
  const hasArtifact = Boolean(message.artifact?.tool)
  const incidents = message.artifact?.incidents ?? []

  // when the answer mapped incidents, drop a small map button at the end of the prose (inline, in
  // the sentence flow) that opens the full map as a modal - only once the answer has finished
  const mapTrigger =
    showActions && incidents.length > 0 ? (
      <button
        onClick={() => setMapOpen(true)}
        aria-label="Show on map"
        className="mx-0.5 inline-flex items-center gap-1 rounded-full bg-accent-soft px-2 py-0.5 align-middle text-[11px] font-medium leading-none text-accent transition-all duration-150 hover:-translate-y-px hover:bg-accent hover:text-white hover:shadow-sm"
      >
        <MapIcon size={12} className="shrink-0" />
        Map
        <span className="font-normal tabular-nums opacity-80">· {incidents.length}</span>
      </button>
    ) : undefined

  return (
    <motion.div
      className="space-y-2.5"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
    >
      <div
        className={cn(
          'max-w-[92%] rounded-2xl border border-hairline bg-panel px-4 py-2.5 text-sm leading-relaxed text-ink',
          message.error && 'border-danger',
        )}
      >
        <ReasoningTrace
          steps={message.steps ?? []}
          reasoning={message.reasoning}
          working={Boolean(message.streaming) && !message.content}
          durationMs={message.artifact?.timing?.total_ms}
        />
        {/* render markdown live as it streams (bold, lists, tables format on arrival, not raw then snap).
            The map button (when present) rides inline at the end of the last sentence. */}
        {message.content && <Markdown trailing={mapTrigger}>{shownContent}</Markdown>}
        {showActions && (
          <div className="mt-2 flex flex-wrap items-center gap-3 text-muted">
            {typeof confidence === 'number' && <TrustChip confidence={confidence} />}
            <button
              onClick={copy}
              className="inline-flex items-center gap-1 text-xs transition-colors hover:text-ink"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            {message.artifact?.tool && (
              <button
                onClick={onInspect}
                className="inline-flex items-center gap-1 text-xs transition-colors hover:text-ink"
              >
                <ScanSearch size={13} /> Inspect
              </button>
            )}
            {hasArtifact && onSelectArtifact && (
              <button
                onClick={onSelectArtifact}
                disabled={isActiveArtifact}
                className={cn(
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors',
                  isActiveArtifact
                    ? 'bg-accent-soft text-accent cursor-default'
                    : 'text-muted hover:bg-panel hover:text-ink',
                )}
              >
                <BrainCircuit size={13} /> {isActiveArtifact ? 'Shown' : 'View'}
              </button>
            )}
          </div>
        )}
      </div>

      {incidents.length > 0 && <MapModal incidents={incidents} open={mapOpen} onOpenChange={setMapOpen} />}
    </motion.div>
  )
}
