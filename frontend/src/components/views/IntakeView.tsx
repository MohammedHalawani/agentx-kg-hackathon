import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, CheckCircle2, Loader2, Send, Square } from 'lucide-react'
import { useComplaintStream } from '../../hooks/useComplaintStream'
import { AflDivider, StageCard } from '../agent/StageCard'
import { cn } from '../../lib/cn'
import type { Stage } from '../../types/agent'

interface Example {
  category: string
  city?: string
  text: string
}

// The verdict banner at the end of a run. Execute and Escalate are both legitimate outcomes
// (the diagram's "Accept -> Execute or Escalate"), so escalation is styled as a considered
// decision, not an error - it is the system declining to act without human judgement.
function Outcome({
  disposition,
  resolutionId,
  loops,
  accepted,
  reviewed,
}: {
  disposition: string
  resolutionId: string | null
  loops: number
  accepted: boolean
  reviewed: boolean
}) {
  const executed = disposition === 'execute'
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'ml-[116px] flex items-start gap-3 rounded-xl border p-3',
        executed ? 'border-chart-good/40 bg-chart-good/5' : 'border-chart-warning/40 bg-chart-warning/5',
      )}
    >
      {executed ? (
        <CheckCircle2 size={18} className="mt-0.5 shrink-0 text-chart-good" />
      ) : (
        <ArrowUpRight size={18} className="mt-0.5 shrink-0 text-chart-warning" />
      )}
      <div className="min-w-0">
        <p className={cn('text-sm font-semibold', executed ? 'text-chart-good' : 'text-chart-warning')}>
          {executed ? 'Executed' : 'Escalated to a human'}
        </p>
        <p className="mt-0.5 text-xs text-muted">
          {executed ? (
            <>
              Written back as <span className="text-ink">{resolutionId}</span>. It is now retrievable precedent for
              future cases — the closed loop.
            </>
          ) : !reviewed ? (
            <>
              Retrieval found no precedent above the similarity floor and no matching shipment, so there was nothing to
              reason from — the pipeline stopped before classifying rather than inventing a decision. A human needs to
              look at this one.
            </>
          ) : accepted ? (
            <>
              The recommendation was accepted, but the complaint never resolved to a shipment in the graph — so there is
              nothing to attach a resolution to, and no record could be written. A human needs to identify the shipment.
            </>
          ) : (
            <>
              The reviewer rejected every candidate after {loops} feedback {loops === 1 ? 'loop' : 'loops'}. Nothing was
              written to the graph.
            </>
          )}
        </p>
      </div>
    </motion.div>
  )
}

// Walks the flat stage list and injects the AFL divider wherever a rejected review is
// followed by another stage - i.e. exactly where the diagram's red feedback edge fires.
function renderTrace(stages: Stage[]) {
  const out = []
  for (let i = 0; i < stages.length; i++) {
    const s = stages[i]
    out.push(<StageCard key={`${s.stage}-${s.loop}-${i}`} stage={s} index={i} />)
    const isRejectedReview = s.stage === 'review' && s.verdict === 'reject'
    const nextIsRetry = stages[i + 1] && stages[i + 1].stage === 'classify'
    if (isRejectedReview && nextIsRetry) out.push(<AflDivider key={`afl-${i}`} reason={s.detail?.reason} />)
  }
  return out
}

export function IntakeView() {
  const { stages, final, busy, error, complaint, run, stop } = useComplaintStream()
  const [text, setText] = useState('')
  const [examples, setExamples] = useState<Example[]>([])

  useEffect(() => {
    fetch('/samples')
      .then((r) => r.json())
      .then((d: { examples?: Example[] }) => setExamples(d.examples ?? []))
      .catch(() => undefined)
  }, [])

  const submit = () => {
    const t = text.trim()
    if (!t || busy) return
    run(t)
    setText('')
  }

  const started = stages.length > 0 || busy || Boolean(error)

  return (
    <div className="flex h-full flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
        {!started ? (
          <div className="mx-auto max-w-2xl pt-10 text-center">
            <h2 className="font-display text-xl font-bold text-ink">Resolve a disrupted shipment</h2>
            <p className="mx-auto mt-2 max-w-lg text-sm text-muted">
              A complaint goes in; three agents classify the root cause, recommend an action grounded in historical
              precedent, and review it against the business rules — then the outcome is written back to the graph.
            </p>
            {examples.length > 0 && (
              <div className="mt-6 space-y-2 text-left">
                <p className="text-center text-xs text-muted">Try one of the live unresolved cases</p>
                {examples.map((ex) => (
                  <button
                    key={ex.text}
                    onClick={() => run(ex.text)}
                    className="flex w-full items-center gap-3 rounded-xl border border-hairline bg-panel px-3 py-2.5 text-left transition-colors hover:border-accent hover:bg-accent-soft"
                  >
                    <span className="min-w-0 flex-1 text-sm text-ink" dir="rtl">
                      {ex.text}
                    </span>
                    <span className="shrink-0 text-[11px] text-muted">{ex.category}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="mx-auto max-w-3xl">
            {complaint && (
              <div className="mb-5 rounded-xl border border-hairline bg-panel p-3">
                <p className="mb-1 text-[11px] font-medium text-muted">Customer complaint</p>
                <p className="text-sm text-ink" dir="auto">
                  {complaint}
                </p>
              </div>
            )}

            <ul className="relative">{renderTrace(stages)}</ul>

            <AnimatePresence>
              {busy && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="ml-[116px] flex items-center gap-2 py-2 text-xs text-muted"
                >
                  <Loader2 size={13} className="animate-spin" />
                  {stages.length === 0 ? 'Starting the pipeline…' : 'Working…'}
                </motion.div>
              )}
            </AnimatePresence>

            {error && (
              <div className="ml-[116px] rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">
                {error}
              </div>
            )}

            {final?.disposition && (
              <Outcome
                disposition={final.disposition}
                resolutionId={final.resolution_id}
                loops={final.loops}
                accepted={final.review?.verdict === 'accept'}
                reviewed={Boolean(final.review)}
              />
            )}
          </div>
        )}
      </div>

      <div className="border-t border-hairline bg-panel px-6 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                submit()
              }
            }}
            rows={1}
            dir="auto"
            placeholder="Describe the problem with the shipment…"
            className="max-h-32 min-h-[40px] flex-1 resize-none rounded-xl border border-hairline bg-surface px-3 py-2.5 text-sm text-ink outline-none placeholder:text-muted focus:border-accent"
          />
          <button
            onClick={busy ? stop : submit}
            disabled={!busy && !text.trim()}
            aria-label={busy ? 'Stop' : 'Run the pipeline'}
            className={cn(
              'flex size-10 shrink-0 items-center justify-center rounded-xl transition-colors',
              busy ? 'bg-danger text-white' : 'bg-accent text-white disabled:bg-hairline disabled:text-muted',
            )}
          >
            {busy ? <Square size={15} /> : <Send size={15} />}
          </button>
        </div>
      </div>
    </div>
  )
}
