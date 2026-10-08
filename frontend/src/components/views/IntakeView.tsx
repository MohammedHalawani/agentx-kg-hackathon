import { useCursorPage } from '@/hooks/useCursorPage'
import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowUpRight, CheckCircle2, RotateCcw, Square } from 'lucide-react'
import { useComplaintStream } from '../../hooks/useComplaintStream'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useOperationsControl, type WorkerStatus, type SimulationStatus, type SimulationSpeed, type ReplayMode } from '@/hooks/useQueueSimulation'
import {
  activeWorkflowState,
} from '@/adapters/v1SamplesAdapter'
import { adaptCase, adaptBuckets, dateBounds, pageQuery, type ApiCase } from '@/adapters/operationsApi'
import type { IntakeFilters, OperationsCase } from '@/contracts/operations'
import { CaseList } from '@/components/operations/CaseList'
import { QueueCounter } from '@/components/operations/QueueCounter'
import { FilterBar, FilterField } from '@/components/operations/FilterBar'
import { SearchInput } from '@/components/operations/SearchInput'
import { DateRangeSelector } from '@/components/operations/DateRangeSelector'
import { CursorPagination } from '@/components/operations/Pagination'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'
import { OperationsCaseDetail } from '@/components/intake/OperationsCaseDetail'
import { CaseWorkspace } from '@/components/intake/CaseWorkspace'
import { ProcessQueuePanel } from '@/components/intake/ProcessQueuePanel'
import { SimulationPanel } from '@/components/intake/SimulationPanel'
import { cn } from '../../lib/cn'
import { operationalLabelKey } from '@/lib/operationalStates'
import type { ExploreShipment } from '../../types/explore'
import { ExploreShipmentCard } from './ExploreShipmentCard'

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
        'mt-4 flex items-start gap-3 rounded-xl border p-3',
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

const DEFAULT_FILTERS: IntakeFilters = {
  search: '',
  timePreset: 'all',
  priority: 'all',
  city: 'all',
  status: 'all',
  cause: 'all',
}

export function IntakeView({ selectedShipment, onClearShipment }: { selectedShipment?: ExploreShipment | null; onClearShipment?: () => void }) {
  const { stages, final, caseFile, busy, error, complaint, stop, reset } = useComplaintStream()
  const { t, isArabic, rootCauseLabel } = useLanguage()
  const worker = useOperationsControl<WorkerStatus>('worker')
  const simulation = useOperationsControl<SimulationStatus>('simulation')
  const [filters, setFilters] = useState<IntakeFilters>(DEFAULT_FILTERS)
  const [operationalStatus, setOperationalStatus] = useState('all')
  const [limit, setLimit] = useState(25)
  const pager = useCursorPage()
  const cursor = pager.cursor
  const cursorStart = pager.offset
  const [selectedCase, setSelectedCase] = useState<OperationsCase | null>(null)
  const [snapshot, setSnapshot] = useState<string | undefined>()
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const query = pageQuery({ search: filters.search, priority: filters.priority, city: filters.city, workflow_state: filters.status, operational_status: operationalStatus, cause: filters.cause, limit, cursor, ...dateBounds(filters.timePreset, snapshot, from, to) })
  const { data, loading, error: queueError, refetch } = useOperationsPage<ApiCase>(`/cases/queue?${query}`)
  const page = { items: (data?.items ?? []).map(adaptCase), total: data?.filtered_total ?? 0, nextCursor: data?.next_cursor ?? null, prevCursor: data?.previous_cursor ?? null }
  const cities = data?.metadata?.filter_choices?.city ?? data?.metadata?.filter_choices?.cities ?? []
  const causes = data?.metadata?.filter_choices?.cause ?? data?.metadata?.filter_choices?.causes ?? []
  const [speed, setSpeed] = useState<SimulationSpeed>(1)
  const [replayMode, setReplayMode] = useState<ReplayMode>('timeline')
  const workerRunning = worker.data?.worker?.state?.toLowerCase() === 'running'
  const simulationRunning = simulation.data?.simulator?.state?.toLowerCase() === 'running'

  const workflowState = final?.workflow_state ?? activeWorkflowState('OPEN', {
    busy,
    hasRecommendation: stages.some((s) => s.stage === 'recommend'),
    hasReview: stages.some((s) => s.stage === 'review'),
    finalDisposition: final?.disposition ?? null,
  })

  useEffect(() => {
    if (final) refetch()
  }, [final, refetch])
  useEffect(() => {
    if (!cursor) refetch()
  }, [worker.data?.worker?.processed_count, simulation.data?.as_of, cursor, refetch])

  const started = stages.length > 0 || busy || Boolean(error)

  const runCase = (caseRow: OperationsCase) => {
    setSelectedCase(caseRow)
  }

  return (
    <div className="flex h-full flex-col">
      <div className={cn('min-h-0 flex-1 px-4 py-4 sm:px-6 sm:py-5', started ? 'overflow-hidden' : 'overflow-y-auto')}>
        {selectedCase || selectedShipment ? <OperationsCaseDetail caseId={selectedCase?.caseId ?? selectedShipment?.case_id ?? undefined} shipmentId={selectedCase?.shipmentId ?? selectedShipment!.shipment_id} onBack={() => { setSelectedCase(null); onClearShipment?.(); refetch() }} /> : !started ? (
          <div className="mx-auto max-w-5xl space-y-4" dir={isArabic ? 'rtl' : undefined}>
            <header>
              <h2 className="font-display text-xl font-bold text-ink">{t('ops.intake.title')}</h2>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('ops.intake.subtitle')}</p>
            </header>

            {data && <section aria-label={t('ops.queue.title')}>
              <h3 className="mb-2 text-sm font-semibold">{t('ops.queue.needsAttention')}</h3>
              <QueueCounter
                counts={adaptBuckets(data?.metadata?.buckets)}
              />
            </section>}

            <FilterBar>
              <FilterField label={t('ops.filters.operational_status')}><select value={operationalStatus} onChange={e => { setOperationalStatus(e.target.value); pager.reset() }} className="rounded-md border border-border bg-card p-1.5"><option value="all">{t('ops.filters.all')}</option>{(data?.metadata?.filter_choices?.operational_status ?? []).map(status => <option key={status} value={status}>{t(operationalLabelKey(status))}</option>)}</select></FilterField>
              <SearchInput
                value={filters.search}
                onChange={(search) => { setFilters((f) => ({ ...f, search })); pager.reset() }}
                placeholder={t('ops.intake.search')}
              />
              <FilterField label={t('ops.filters.priority')}>
                <select
                  value={filters.priority}
                  onChange={(e) => { setFilters((f) => ({ ...f, priority: e.target.value as IntakeFilters['priority'] })); pager.reset() }}
                  className="rounded-md border border-border bg-card px-2 py-1.5 text-sm"
                >
                  <option value="all">{t('ops.filters.all')}</option>
                  <option value="high">{t('ops.priority.high')}</option>
                  <option value="medium">{t('ops.priority.medium')}</option>
                  <option value="low">{t('ops.priority.low')}</option>
                </select>
              </FilterField>
              <FilterField label={t('ops.filters.city')}>
                <select
                  value={filters.city}
                  onChange={(e) => { setFilters((f) => ({ ...f, city: e.target.value })); pager.reset() }}
                  className="rounded-md border border-border bg-card px-2 py-1.5 text-sm"
                >
                  <option value="all">{t('ops.filters.all')}</option>
                  {cities.map((city) => <option key={city} value={city}>{city}</option>)}
                </select>
              </FilterField>
              <FilterField label={t('ops.filters.cause')}>
                <select
                  value={filters.cause}
                  onChange={(e) => { setFilters((f) => ({ ...f, cause: e.target.value })); pager.reset() }}
                  className="rounded-md border border-border bg-card px-2 py-1.5 text-sm"
                >
                  <option value="all">{t('ops.filters.all')}</option>
                  {causes.map((cause) => <option key={cause} value={cause}>{rootCauseLabel(cause)}</option>)}
                </select>
              </FilterField>
              <FilterField label={t('ops.filters.workflow')}><select value={filters.status} onChange={e => { setFilters(f => ({ ...f, status: e.target.value as IntakeFilters['status'] })); pager.reset() }} className="rounded-md border border-border bg-card p-1.5"><option value="all">{t('ops.filters.all')}</option>{(data?.metadata?.filter_choices?.workflow_state ?? Object.keys(data?.metadata?.buckets ?? {})).map(s => <option key={s} value={s}>{t(`ops.states.${s}`)}</option>)}</select></FilterField>
            </FilterBar>
            <DateRangeSelector
              value={filters.timePreset}
              onChange={(timePreset) => { setFilters((f) => ({ ...f, timePreset })); setSnapshot(data?.metadata?.as_of); pager.reset() }}
            />
            {filters.timePreset === 'custom' && <div className="flex flex-wrap gap-2"><label>{t('ops.filters.from')} <input type="date" value={from} onChange={e => { setFrom(e.target.value); pager.reset() }} /></label><label>{t('ops.filters.to')} <input type="date" value={to} onChange={e => { setTo(e.target.value); pager.reset() }} /></label></div>}

            {selectedShipment && (
              <ExploreShipmentCard shipment={selectedShipment} onOpenCase={() => undefined} actionLabel={t('explore.analyzeCase')} />
            )}

            {worker.data && <ProcessQueuePanel
              running={workerRunning}
              onToggle={() => void worker.command(workerRunning ? 'pause' : 'start')}
              disabled={worker.pending || !worker.data || Boolean(worker.error)}
              onStep={() => void worker.command('tick')}
              concurrency={1}
              processingId={worker.data?.worker?.active_case_id ?? null}
              queueDepth={page.total}
              needsReview={adaptBuckets(data?.metadata?.buckets).needsReview}
            />}
            {worker.error && <ErrorState onRetry={worker.refetch} />}
            {worker.loading && !worker.data && <LoadingState label={t('ops.loading')} />}

            {simulation.data && <SimulationPanel
              running={simulationRunning}
              onRunningChange={(v) => void simulation.command(v ? 'start' : 'pause', v ? { speed, replay_mode: replayMode } : {})}
              speed={simulationRunning ? simulation.data!.simulator.speed : speed}
              onSpeedChange={(v) => { setSpeed(v); if (simulationRunning) void simulation.command('start', { speed: v, replay_mode: simulation.data?.simulator.replay_mode ?? replayMode }) }}
              replayMode={simulationRunning ? simulation.data?.simulator.replay_mode ?? replayMode : replayMode}
              onReplayModeChange={v => { setReplayMode(v); if (simulationRunning) void simulation.command('start', { speed: simulation.data?.simulator.speed ?? speed, replay_mode: v }) }}
              events={[]}
              disabled={simulation.pending || !simulation.data || Boolean(simulation.error)}
              eventCount={simulation.data?.simulator?.event_count}
              asOf={simulation.data?.as_of}
              onStep={() => void simulation.command('tick', { seconds: 60 })}
            />}
            {simulation.error && <ErrorState onRetry={simulation.refetch} />}
            {simulation.loading && !simulation.data && <LoadingState label={t('ops.loading')} />}

            {loading ? (
              <LoadingState label={t('intake.loading')} />
            ) : queueError ? <ErrorState onRetry={refetch} /> : (
              <>
                <CaseList
                  cases={page.items}
                  onSelect={runCase}
                  emptyTitle={t('intake.emptyTitle')}
                  emptyDescription={t('intake.emptyDescription')}
                />
                <CursorPagination
                  total={page.total}
                  limit={limit}
                  cursorStart={cursorStart}
                  nextCursor={page.nextCursor}
                  prevCursor={pager.hasPrevious ? 'visited-page' : null}
                  onNext={() => pager.next(page.nextCursor, limit)}
                  onPrev={() => pager.previous(limit)}
                  onLimitChange={(n) => { setLimit(n); pager.reset() }}
                />
              </>
            )}
          </div>
        ) : (
          <CaseWorkspace
            workflowState={workflowState}
            complaint={complaint}
            stages={stages}
            final={final}
            caseFile={caseFile}
            busy={busy}
            error={error}
            outcome={
              final?.disposition ? (
                <Outcome
                  disposition={final.disposition}
                  resolutionId={final.resolution_id}
                  loops={final.loops}
                  accepted={final.review?.verdict === 'accept'}
                  reviewed={Boolean(final.review)}
                />
              ) : null
            }
          />
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
