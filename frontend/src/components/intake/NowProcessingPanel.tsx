import { useEffect, useState } from 'react'
import { Check, Circle, Loader2, RotateCcw, UserRound, X } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useCasePipeline } from '@/hooks/useCasePipeline'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import type { PipelineEvent } from '@/contracts/caseDetail'
import type { WorkerStatus } from '@/hooks/useQueueSimulation'
import { cn } from '@/lib/cn'

const STEPS: [string, string[]][] = [
  ['collect', ['extract']], ['graph', ['retrieve']], ['diagnose', ['classify']], ['precedent', ['retrieve_context']],
  ['recommend', ['recommend']], ['review', ['review']], ['route', ['writeback', 'escalate']],
]
const NOOP = () => {}

/** Polls worker status quickly while auto-triage runs, so a claim is visible within ~1s. */
export function useLiveWorkerStatus(running: boolean, initial: WorkerStatus | null) {
  const [status, setStatus] = useState<WorkerStatus | null>(initial)
  useEffect(() => { if (initial) setStatus(initial) }, [initial])
  useEffect(() => {
    if (!running) return
    let alive = true
    const poll = () => fetch('/worker/status').then(r => (r.ok ? r.json() : null)).then(v => { if (alive && v?.worker) setStatus(v) }).catch(() => {})
    const timer = setInterval(poll, 1200)
    return () => { alive = false; clearInterval(timer) }
  }, [running])
  return status
}

function stepState(events: PipelineEvent[], stages: string[]) {
  const own = events.filter(e => stages.includes(e.stage))
  return own.at(-1)?.status ?? 'QUEUED'
}

function Glyph({ status }: { status: string }) {
  if (status === 'COMPLETED') return <Check size={12} aria-hidden="true" />
  if (status === 'RUNNING' || status === 'RETRYING') return <Loader2 size={12} className="animate-spin" aria-hidden="true" />
  if (status === 'REJECTED') return <RotateCcw size={12} aria-hidden="true" />
  if (status === 'FAILED') return <X size={12} aria-hidden="true" />
  return <Circle size={10} aria-hidden="true" />
}

/**
 * Real worker/run state only: the active claim (or the most recent completed run) and its recorded
 * stage events from the case SSE stream. No timers fabricate progress.
 */
export function NowProcessingPanel({ status, running, onOpen }: {
  status: WorkerStatus | null
  running: boolean
  onOpen: (caseId: string, shipmentId: string) => void
}) {
  const { t } = useLanguage()
  const w = status?.worker
  const activeId = w?.active_case_id ?? null
  const caseId = activeId ?? w?.last_case_id ?? undefined
  const { live } = useCasePipeline(caseId, NOOP)
  const events = live?.events ?? []
  const routed = live?.workflow_state ?? w?.last_workflow_state
  const isActive = Boolean(activeId) && live?.status !== 'REVIEWED'
  const startedAt = events[0]?.recorded_at
  const endedAt = events.at(-1)?.recorded_at
  const ms = startedAt && endedAt ? Math.max(0, Date.parse(endedAt) - Date.parse(startedAt)) : null
  const human = routed && ['HUMAN_REVIEW', 'AWAITING_APPROVAL', 'NEEDS_EVIDENCE', 'ESCALATED'].includes(routed)

  return (
    <Card size="sm" className="gap-2 px-3 py-3" aria-live="polite" data-testid="now-processing">
      <div className="flex items-center gap-2">
        <span className={cn('size-2 rounded-full', running ? 'animate-pulse bg-chart-good' : 'bg-muted-foreground/40')} aria-hidden="true" />
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {isActive ? t('ops.live.nowProcessing') : t('ops.live.lastProcessed')}
        </h3>
        {caseId && (
          <Button size="xs" variant="outline" className="ms-auto" onClick={() => onOpen(caseId, (activeId ? w?.active_shipment_id : w?.last_shipment_id) ?? '')}>
            {isActive ? t('ops.live.openLive') : t('ops.live.openCase')}
          </Button>
        )}
      </div>
      {!caseId ? (
        <p className="text-xs text-muted-foreground">{running ? t('ops.live.waiting') : t('ops.live.idle')}</p>
      ) : (
        <>
          <p className="font-mono text-sm font-semibold" dir="ltr">{(activeId ? w?.active_shipment_id : w?.last_shipment_id) ?? caseId}</p>
          <ol className="flex flex-wrap items-center gap-1" aria-label={t('ops.pipeline.stages')}>
            {STEPS.map(([key, stages]) => {
              const s = stepState(events, stages)
              return (
                <li key={key} className={cn('inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] transition-colors duration-300',
                  s === 'COMPLETED' ? 'border-chart-good/40 text-foreground' : s === 'RUNNING' || s === 'RETRYING' ? 'border-primary bg-primary/10 text-primary' : s === 'REJECTED' ? 'border-chart-warning/50 text-chart-warning' : 'border-border text-muted-foreground')}>
                  <Glyph status={s} />{t(`ops.pipeline.short.${key}`)}
                </li>
              )
            })}
          </ol>
          {!isActive && routed && (
            <p className={cn('flex items-center gap-1.5 text-xs', human ? 'text-chart-warning' : 'text-muted-foreground')}>
              {human && <UserRound size={12} aria-hidden="true" />}
              {t('ops.live.routed', { state: t(`ops.states.${routed}`) })}
              {ms != null && <span className="text-muted-foreground">· {t('ops.live.recordedIn', { ms: String(ms) })}</span>}
            </p>
          )}
          {!isActive && human && running && <p className="text-[11px] text-muted-foreground">{t('ops.live.continues')}</p>}
        </>
      )}
    </Card>
  )
}
