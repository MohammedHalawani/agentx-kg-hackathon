import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { BookOpen, Check, ChevronRight, Database, Loader2, Map as MapIcon, MapPin } from 'lucide-react'
import type { Step } from '../../types/contract'

interface ReasoningTraceProps {
  steps: Step[]
  reasoning?: string
  working: boolean
  durationMs?: number
}

// a step's tool → a glyph for the kind of work it is, so the trace reads as distinct agent actions
const STEP_ICON: Record<string, typeof BookOpen> = {
  get_ontology: BookOpen,
  geocode_place: MapPin,
  text2cypher: Database,
  show_on_map: MapIcon,
}

// The agent's "thinking" as a live checklist: a ticking timer while it works, a spinner on the step
// it's running and a check on the ones it finished, collapsing to "Thought for Ns" when done. When the
// model exposes its own reasoning text (some reasoning models do), that stands in for the steps.
export function ReasoningTrace({ steps, reasoning, working, durationMs }: ReasoningTraceProps) {
  const [open, setOpen] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const hasReasoning = Boolean(reasoning?.trim())
  const hasBody = hasReasoning || steps.length > 0

  // tick a live timer while the agent works, so the wait reads as active work; reset on each run
  useEffect(() => {
    if (!working) return
    const start = Date.now()
    setElapsed(0)
    const id = setInterval(() => setElapsed((Date.now() - start) / 1000), 100)
    return () => clearInterval(id)
  }, [working])

  if (!hasBody && !working) return null

  const expanded = working || open
  const header = working
    ? `Thinking ${elapsed.toFixed(1)}s`
    : durationMs
      ? `Thought for ${(durationMs / 1000).toFixed(1)}s`
      : 'Thought process'

  return (
    <div className="mb-2 text-xs">
      <button
        onClick={() => !working && setOpen((o) => !o)}
        aria-expanded={expanded}
        disabled={working}
        className="group flex items-center gap-1 text-left"
      >
        {!working && (
          <ChevronRight
            size={12}
            className={`shrink-0 text-muted transition-transform ${open ? 'rotate-90' : ''}`}
          />
        )}
        <span className={working ? 'shimmer font-medium' : 'text-muted transition-colors group-hover:text-ink'}>
          {header}
        </span>
      </button>

      <AnimatePresence initial={false}>
        {expanded && hasBody && (
          <motion.div
            key="body"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.18, ease: 'easeOut' }}
            className="ml-[5px] mt-1.5 space-y-1.5 border-l border-hairline pl-3 leading-relaxed text-muted"
          >
            {hasReasoning && <p className="whitespace-pre-wrap italic opacity-90">{reasoning}</p>}
            {steps.map((s, i) => {
              // the last step is the one running while the agent works; earlier ones are done
              const running = working && !hasReasoning && i === steps.length - 1
              const Icon = STEP_ICON[s.tool]
              return (
                <motion.div
                  key={i}
                  initial={{ opacity: 0, x: -4 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.18, ease: 'easeOut' }}
                  className="flex items-start gap-1.5"
                >
                  <span className="mt-[2px] shrink-0">
                    {running ? (
                      <Loader2 size={11} className="animate-spin text-accent motion-reduce:animate-none" />
                    ) : (
                      <Check size={11} className="text-muted" />
                    )}
                  </span>
                  {Icon && <Icon size={12} className="mt-[2px] shrink-0 opacity-70" />}
                  <span className={running ? 'shimmer' : undefined}>
                    {s.label}
                    {s.detail ? <span className="opacity-70"> · {s.detail}</span> : null}
                  </span>
                </motion.div>
              )
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
