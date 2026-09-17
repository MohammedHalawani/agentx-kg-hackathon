import { useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, CheckCircle2, Loader2, Play, RotateCcw, Square } from 'lucide-react'
import { useComplaintStream } from '../../hooks/useComplaintStream'
import { useFetch } from '../../hooks/useFetch'
import { Skeleton } from '../ui/Skeleton'
import { AflDivider, StageCard } from '../agent/StageCard'
import { CaseFile } from '../agent/CaseFile'
import { cn } from '../../lib/cn'
import type { Stage } from '../../types/agent'

interface OpenCase {
  failure_id: string
  shipment_id: string
  category: string
  city?: string
  courier?: string
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
              written to the graph — the rejection reasons above, and the case file below, are what a human picks this
              up with.
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
  const { stages, final, caseFile, busy, error, complaint, run, stop, reset } = useComplaintStream()
  const { data, loading, refetch } = useFetch<{ cases: OpenCase[] }>('/samples')
  const openCases = data?.cases ?? []

  // Re-read the queue once a run finishes: an executed case has just had :RESOLVES_WITH
  // written, so it is no longer open and should disappear from the list rather than sit
  // there waiting to be clicked again (which would now escalate, looking like a bug).
  useEffect(() => {
    if (final) refetch()
  }, [final, refetch])

  const started = stages.length > 0 || busy || Boolean(error)

  return (
    <div className="flex h-full flex-col">
      <div className={cn('min-h-0 flex-1 px-6 py-5', started ? 'overflow-hidden' : 'overflow-y-auto')}>
        {!started ? (
          <div className="mx-auto max-w-3xl">
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 className="font-display text-xl font-bold text-ink">Open cases</h2>
              <span className="text-sm text-muted">
                {loading ? 'loading…' : `${openCases.length} shipment${openCases.length === 1 ? '' : 's'} awaiting a decision`}
              </span>
            </div>
            <p className="mt-1.5 max-w-2xl text-sm text-muted">
              Pick one to run it. Three agents classify the root cause, recommend an action grounded in historical
              precedent, and review it against the business rules — then the outcome is written back to the graph, or
              the case is handed to a human. A case you resolve leaves this list.
            </p>

            <div className="mt-5 space-y-2">
              {loading && Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}

              {!loading && openCases.length === 0 && (
                <div className="rounded-xl border border-hairline bg-panel px-4 py-8 text-center">
                  <p className="text-sm font-medium text-ink">No open cases left</p>
                  <p className="mt-1 text-xs text-muted">
                    Every failure in the graph now carries a resolution. Restore the dataset to work through them again.
                  </p>
                </div>
              )}

              {openCases.map((c) => (
                <button
                  key={c.failure_id}
                  onClick={() => run(c.text)}
                  className="flex w-full items-center gap-3 rounded-xl border border-hairline bg-panel px-3 py-2.5 text-left transition-colors hover:border-accent hover:bg-accent-soft"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink" dir="rtl">
                      {c.text}
                    </span>
                    <span className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-muted">
                      <span className="font-mono">{c.shipment_id}</span>
                      <span>{c.category.replace(/_/g, ' ')}</span>
                      {c.city && <span dir="auto">{c.city}</span>}
                      {c.courier && <span dir="auto">{c.courier}</span>}
                    </span>
                  </span>
                  <Play size={14} className="shrink-0 text-muted" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Two panes once a run starts: the reasoning on the left, the shipment's own
             evidence on the right. The evidence is always open - it is what the decision was
             made from, so hiding it behind a disclosure made the most useful half of the
             screen opt-in. Stacks on a narrow viewport, where side-by-side would leave both
             halves too cramped to read. */
          <div className="mx-auto flex h-full max-w-[1600px] flex-col gap-4 lg:flex-row">
            <div className="min-h-0 flex-1 overflow-y-auto lg:max-w-3xl">
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

            {caseFile && (
              <div className="min-h-[520px] flex-1 lg:min-h-0 lg:max-w-[640px]">
                <CaseFile data={caseFile} />
              </div>
            )}
          </div>
        )}
      </div>

      {/* No free-text composer: a run can only be started from a real unresolved case, so
          arbitrary text never reaches the pipeline or the graph. This bar is just the run
          controls - stop while it works, start another once it's done. */}
      {started && (
        <div className="border-t border-hairline bg-panel px-6 py-3">
          <div className="mx-auto flex max-w-3xl items-center gap-2">
            {busy ? (
              <button
                onClick={stop}
                className="inline-flex items-center gap-2 rounded-xl bg-danger px-3 py-2 text-sm font-medium text-white"
              >
                <Square size={14} /> Stop
              </button>
            ) : (
              <button
                onClick={reset}
                className="inline-flex items-center gap-2 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-white"
              >
                <RotateCcw size={14} /> Run another case
              </button>
            )}
            <span className="text-xs text-muted">
              {busy ? 'The pipeline is running…' : 'Pick another unresolved case from the queue.'}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
