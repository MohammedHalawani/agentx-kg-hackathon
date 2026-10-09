import { useCursorPage } from '@/hooks/useCursorPage'
import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { ArrowUpRight, CheckCircle2, Loader2, RotateCcw, Square } from 'lucide-react'
import { useComplaintStream } from '../../hooks/useComplaintStream'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useOperationsControl, type WorkerStatus, type SimulationStatus, type SimulationSpeed, type ReplayMode } from '@/hooks/useQueueSimulation'
import {
  activeWorkflowState,
} from '@/adapters/v1SamplesAdapter'
import { adaptCase, adaptBuckets, dateBounds, pageQuery, type ApiCase } from '@/adapters/operationsApi'
import type { IntakeFilters, OperationsCase, QueueBucketCounts } from '@/contracts/operations'
import { ResponsiveDisclosure } from '@/components/operations/ResponsiveDisclosure'
import { QueueCounter } from '@/components/operations/QueueCounter'
import { IntakeToolbar } from '@/components/operations/IntakeToolbar'
import { QueueCasesTable } from '@/components/operations/QueueCasesTable'
import { CursorPagination } from '@/components/operations/Pagination'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'
import { OperationsCaseDetail } from '@/components/intake/OperationsCaseDetail'
import { CaseWorkspace } from '@/components/intake/CaseWorkspace'
import { ProcessQueuePanel } from '@/components/intake/ProcessQueuePanel'
import { SimulationPanel } from '@/components/intake/SimulationPanel'
import { NowProcessingPanel, useLiveWorkerStatus } from '@/components/intake/NowProcessingPanel'
import { HumanAttentionRail } from '@/components/intake/HumanAttentionRail'
import { cn } from '../../lib/cn'
import type { ExploreShipment } from '../../types/explore'

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

type BucketKey = keyof QueueBucketCounts

function workflowForBucket(key: BucketKey): IntakeFilters['status'] {
  const map: Partial<Record<BucketKey, IntakeFilters['status']>> = {
    open: 'OPEN',
    investigating: 'INVESTIGATING',
    needsReview: 'HUMAN_REVIEW',
    needsEvidence: 'NEEDS_EVIDENCE',
    awaitingApproval: 'AWAITING_APPROVAL',
    awaitingOutcome: 'AWAITING_OUTCOME',
    resolved: 'RESOLVED',
  }
  return map[key] ?? 'all'
}

const DEFAULT_FILTERS: IntakeFilters = {
  search: '',
  timePreset: 'all',
  priority: 'all',
  city: 'all',
  status: 'all',
  cause: 'all',
}

export function IntakeView({
  selectedShipment,
  onClearShipment,
  onExploreShipment,
  onOpenAudit,
}: {
  selectedShipment?: Pick<ExploreShipment, 'shipment_id' | 'case_id'> | null
  onClearShipment?: () => void
  onExploreShipment?: (row: OperationsCase) => void
  onOpenAudit?: (row: OperationsCase) => void
}) {
  const { stages, final, caseFile, busy, error, complaint, stop, reset } = useComplaintStream()
  const { t, isArabic } = useLanguage()
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
  const queueRefreshing = loading && data != null
  const queueInitialLoad = loading && !data
  const page = { items: (data?.items ?? []).map(adaptCase), total: data?.filtered_total ?? 0, nextCursor: data?.next_cursor ?? null, prevCursor: data?.previous_cursor ?? null }
  // Unfiltered lifecycle totals for counters and the Human attention rail, independent of table filters.
  const unfiltered = query === 'limit=25'
  const totals = useOperationsPage<ApiCase>('/cases/queue?limit=25', !unfiltered)
  const totalBuckets = (unfiltered ? data : totals.data)?.metadata?.buckets ?? {}
  const bucketCounts = adaptBuckets(totalBuckets)
  const [railCollapsed, setRailCollapsed] = useState(false)
  const [activeBucket, setActiveBucket] = useState<BucketKey | undefined>()
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
  const live = useLiveWorkerStatus(workerRunning, worker.data)
  const liveTick = `${live?.worker?.processed_count}|${live?.worker?.active_case_id}|${simulation.data?.as_of}`
  const refetchTotals = totals.refetch
  useEffect(() => {
    // Background refresh keeps rows mounted (keepDataOnRefresh); only changed rows re-render.
    if (!cursor) refetch()
    if (!unfiltered) refetchTotals()
  }, [unfiltered, liveTick, cursor, refetch, refetchTotals])

  const started = stages.length > 0 || busy || Boolean(error)

  const runCase = (caseRow: OperationsCase) => {
    setSelectedCase(caseRow)
  }

  return (
    <div className="flex h-full flex-col">
      <div className={cn('min-h-0 flex-1 px-4 py-4 sm:px-6 sm:py-5', started ? 'overflow-hidden' : 'overflow-y-auto')}>
        {selectedCase || selectedShipment ? <OperationsCaseDetail caseId={selectedCase?.caseId ?? selectedShipment?.case_id ?? undefined} shipmentId={selectedCase?.shipmentId ?? selectedShipment!.shipment_id} onBack={() => { setSelectedCase(null); onClearShipment?.(); refetch() }} /> : !started ? (
          <div className="mx-auto max-w-[1760px] space-y-4" dir={isArabic ? 'rtl' : undefined}>
            <header>
              <h2 className="font-display text-xl font-bold text-ink">{t('ops.intake.title')}</h2>
              <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('ops.intake.subtitle')}</p>
            </header>

            <section aria-label={t('ops.queue.title')}>
              <div className="mb-2 flex flex-wrap items-center gap-2" role="status">
                <h3 className="text-sm font-semibold">
                  {t('ops.automation.autoTriage')}: {t(`ops.automation.${worker.error ? 'UNAVAILABLE' : worker.data ? workerRunning ? 'RUNNING' : 'PAUSED' : 'UNAVAILABLE'}`)}
                </h3>
                {worker.data?.worker?.active_case_id && (
                  <span className="font-mono text-xs text-muted-foreground" dir="ltr">{worker.data.worker.active_case_id}</span>
                )}
                {worker.data && (
                  <button
                    type="button"
                    disabled={worker.pending || Boolean(worker.error)}
                    onClick={() => void worker.command(workerRunning ? 'pause' : 'start')}
                    className={cn(
                      'ms-auto inline-flex items-center gap-1.5 rounded-lg px-3 py-1 text-xs font-medium disabled:opacity-50',
                      workerRunning ? 'border border-border bg-card' : 'bg-primary text-primary-foreground',
                    )}
                  >
                    {worker.pending ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                    {t(workerRunning ? 'ops.queue.pause' : 'ops.queue.start')}
                  </button>
                )}
              </div>
              <p className="mb-2 text-xs text-muted-foreground">{t('ops.automation.queueContinues')}</p>
              <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(320px,420px)]">
              <QueueCounter
                counts={bucketCounts}
                active={activeBucket}
                onSelect={(key) => {
                  if (key === 'human') { setRailCollapsed(false); return }
                  const next = workflowForBucket(key)
                  setActiveBucket(key)
                  setFilters((f) => ({ ...f, status: next }))
                  pager.reset()
                }}
              />
              <NowProcessingPanel status={live} running={workerRunning} onOpen={(caseId, shipmentId) => setSelectedCase({ caseId, shipmentId, issueSummary: '', priority: 'unknown', workflowState: 'INVESTIGATING' } as OperationsCase)} />
              </div>
            </section>

            <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1 space-y-4">

            <IntakeToolbar
              filters={filters}
              operationalStatus={operationalStatus}
              operationalChoices={data?.metadata?.filter_choices?.operational_status ?? []}
              cities={cities}
              causes={causes}
              workflowChoices={data?.metadata?.filter_choices?.workflow_state ?? Object.keys(data?.metadata?.buckets ?? {})}
              onFiltersChange={(patch) => { setFilters((f) => ({ ...f, ...patch })); setActiveBucket(undefined); pager.reset() }}
              onOperationalStatusChange={(value) => { setOperationalStatus(value); pager.reset() }}
              onTimePresetChange={(timePreset) => { setFilters((f) => ({ ...f, timePreset })); setSnapshot(data?.metadata?.as_of); pager.reset() }}
              customFrom={from}
              customTo={to}
              onCustomFrom={(v) => { setFrom(v); pager.reset() }}
              onCustomTo={(v) => { setTo(v); pager.reset() }}
              limit={limit}
              onLimitChange={(n) => { setLimit(n); pager.reset() }}
              onRefresh={refetch}
              refreshing={queueRefreshing}
            />
            <ResponsiveDisclosure title={t('ops.disclosure.controls')} defaultOpen={false}>
            {worker.data && <ProcessQueuePanel
              running={workerRunning}
              onToggle={() => void worker.command(workerRunning ? 'pause' : 'start')}
              hideToggle
              disabled={worker.pending || !worker.data || Boolean(worker.error)}
              onStep={() => void worker.command('tick')}
              concurrency={1}
              processingId={worker.data?.worker?.active_case_id ?? null}
              queueDepth={(data?.metadata?.buckets?.OPEN ?? 0) + (data?.metadata?.buckets?.REOPENED ?? 0)}
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
              onStep={() => void simulation.command('tick', { seconds: 60, speed: simulationRunning ? simulation.data!.simulator.speed : speed, replay_mode: simulationRunning ? simulation.data!.simulator.replay_mode : replayMode })}
            />}
            {simulation.error && <ErrorState onRetry={simulation.refetch} />}
            {simulation.loading && !simulation.data && <LoadingState label={t('ops.loading')} />}

            </ResponsiveDisclosure>
            {queueInitialLoad ? (
              <LoadingState label={t('intake.loading')} />
            ) : queueError ? <ErrorState onRetry={refetch} /> : (
              <>
                <QueueCasesTable
                  cases={page.items}
                  refreshing={queueRefreshing}
                  emptyTitle={t('intake.emptyTitle')}
                  emptyDescription={t('intake.emptyDescription')}
                  actions={{
                    onOpen: runCase,
                    onCopyId: (row) => void navigator.clipboard?.writeText(row.caseId),
                    onExplore: onExploreShipment,
                    onAudit: onOpenAudit,
                  }}
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
            <div className="sticky top-0 hidden max-h-[calc(100vh-7rem)] self-stretch lg:flex">
              <HumanAttentionRail counts={totalBuckets} refreshKey={liveTick} onOpen={runCase} collapsed={railCollapsed} onCollapsedChange={setRailCollapsed} />
            </div>
            </div>
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
