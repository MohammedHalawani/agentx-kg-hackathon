import { useEffect } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowUpRight, CheckCircle2, Loader2, Play, RotateCcw, Square } from 'lucide-react'
import { useComplaintStream } from '../../hooks/useComplaintStream'
import { useFetch } from '../../hooks/useFetch'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Skeleton } from '../ui/skeleton'
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
  const { t } = useLanguage()
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
          {executed ? t('intake.executed') : t('intake.escalated')}
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {executed
            ? t('intake.outcomeExecuted', { id: resolutionId ?? '—' })
            : !reviewed
              ? t('intake.outcomeNoReview')
              : accepted
                ? t('intake.outcomeNoShipment')
                : t('intake.outcomeRejected', { loops })}
        </p>
      </div>
    </motion.div>
  )
}

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
  const { t, rootCauseLabel } = useLanguage()
  const openCases = data?.cases ?? []

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
              <h2 className="font-display text-xl font-bold text-ink">{t('intake.title')}</h2>
              <span className="text-sm text-muted-foreground">
                {loading
                  ? t('intake.loading')
                  : t('intake.awaiting', { count: openCases.length })}
              </span>
            </div>
            <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">{t('intake.description')}</p>

            <div className="mt-5 space-y-2">
              {loading && Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-16 rounded-xl" />)}

              {!loading && openCases.length === 0 && (
                <div className="rounded-xl border border-hairline bg-panel px-4 py-8 text-center">
                  <p className="text-sm font-medium text-ink">{t('intake.emptyTitle')}</p>
                  <p className="mt-1 text-xs text-muted-foreground">{t('intake.emptyDescription')}</p>
                </div>
              )}

              {openCases.map((c) => (
                <button
                  key={c.failure_id}
                  onClick={() => run(c.text)}
                  className="group flex w-full items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-primary/35 hover:bg-accent hover:text-accent-foreground"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-ink group-hover:text-accent-foreground" dir="auto">
                      {c.text}
                    </span>
                    <span className="mt-0.5 flex flex-wrap gap-x-2 text-[11px] text-muted-foreground group-hover:text-accent-foreground/80">
                      <span className="font-mono" dir="ltr">
                        {c.shipment_id}
                      </span>
                      <span>{rootCauseLabel(c.category)}</span>
                      {c.city && <span dir="auto">{c.city}</span>}
                      {c.courier && <span dir="auto">{c.courier}</span>}
                    </span>
                  </span>
                  <Play size={14} className="shrink-0 text-muted-foreground" />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex h-full max-w-[1600px] flex-col gap-4 lg:flex-row">
            <div className="min-h-0 flex-1 overflow-y-auto lg:max-w-3xl">
              {complaint && (
                <div className="mb-5 rounded-xl border border-hairline bg-panel p-3">
                  <p className="mb-1 text-[11px] font-medium text-muted-foreground">{t('intake.complaint')}</p>
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
                    className="ml-[116px] flex items-center gap-2 py-2 text-xs text-muted-foreground"
                  >
                    <Loader2 size={13} className="animate-spin" />
                    {stages.length === 0 ? t('intake.starting') : t('intake.working')}
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

      {started && (
        <div className="border-t border-border bg-card px-6 py-3">
          <div className="mx-auto flex max-w-3xl items-center gap-2">
            {busy ? (
              <button
                onClick={stop}
                className="inline-flex items-center gap-2 rounded-xl bg-danger px-3 py-2 text-sm font-medium text-white"
              >
                <Square size={14} /> {t('intake.stop')}
              </button>
            ) : (
              <button
                onClick={reset}
                className="inline-flex items-center gap-2 rounded-xl bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
              >
                <RotateCcw size={14} /> {t('intake.runAnother')}
              </button>
            )}
            <span className="text-xs text-muted-foreground">
              {busy ? t('intake.pipelineRunning') : t('intake.pickAnother')}
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
