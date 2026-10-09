import { useMemo, useState } from 'react'
import { useFetch } from '@/hooks/useFetch'
import { useCursorPage } from '@/hooks/useCursorPage'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { OperationalMetric } from '@/components/operations/OperationalMetric'
import { ErrorState } from '@/components/operations/ErrorState'
import { LoadingState } from '@/components/operations/LoadingState'
import { QueueCasesTable } from '@/components/operations/QueueCasesTable'
import { CursorPagination } from '@/components/operations/Pagination'
import { adaptCase, pageQuery, type ApiCase } from '@/adapters/operationsApi'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface DecisionMetrics {
  case_counts?: Record<string, number>
  verified_outcome_count: number
  succeeded: number
  failed: number
  pending_outcome_count?: number
  verified_success_rate: number | null
  denominator: string
}
interface DecisionsData {
  as_of: string
  synthetic: boolean
  development: DecisionMetrics
  history: DecisionMetrics
  limitations?: string[]
}

type TabKey = 'overview' | 'AWAITING_APPROVAL' | 'HUMAN_REVIEW' | 'AWAITING_OUTCOME' | 'RESOLVED' | 'learning'

const TABS: { key: TabKey; labelKey: string }[] = [
  { key: 'overview', labelKey: 'ops.decisionsPage.overview' },
  { key: 'AWAITING_APPROVAL', labelKey: 'ops.decisionsPage.awaitingApproval' },
  { key: 'HUMAN_REVIEW', labelKey: 'ops.decisionsPage.humanReview' },
  { key: 'AWAITING_OUTCOME', labelKey: 'ops.decisionsPage.awaitingOutcome' },
  { key: 'RESOLVED', labelKey: 'ops.decisionsPage.resolved' },
  { key: 'learning', labelKey: 'ops.decisionsPage.learning' },
]

export function OperationsDecisionsView() {
  const { data: metrics, loading: metricsLoading, error: metricsError, refetch: refetchMetrics } = useFetch<DecisionsData>('/decisions', true)
  const { t, isArabic } = useLanguage()
  const [tab, setTab] = useState<TabKey>('overview')
  const [limit, setLimit] = useState(25)
  const pager = useCursorPage()
  const workflowFilter = tab !== 'overview' && tab !== 'learning' ? tab : undefined
  const query = useMemo(
    () => pageQuery({ limit, cursor: pager.cursor, workflow_state: workflowFilter }),
    [limit, pager.cursor, workflowFilter],
  )
  const showQueue = tab !== 'overview' && tab !== 'learning'
  const queueUrl = `/cases/queue?${query}`
  const { data: queue, loading: queueLoading, error: queueError, refetch: refetchQueue } = useOperationsPage<ApiCase>(queueUrl, showQueue)
  const page = {
    items: (queue?.items ?? []).map(adaptCase),
    total: queue?.filtered_total ?? 0,
    nextCursor: queue?.next_cursor ?? null,
  }
  const queueRefreshing = queueLoading && queue != null
  const dev = metrics?.development

  return (
    <div className="flex h-full flex-col overflow-hidden" dir={isArabic ? 'rtl' : 'ltr'}>
      <div className="shrink-0 space-y-3 border-b border-border px-4 py-4 sm:px-6">
        <h2 className="font-display text-xl font-bold text-ink">{t('nav.decisions')}</h2>
        <p className="text-sm text-muted-foreground">{t('ops.outcomeMetrics.explanation')}</p>
        <Tabs value={tab} onValueChange={(value) => { setTab(value as TabKey); pager.reset() }} className="gap-0">
          <TabsList className="h-auto flex-wrap gap-1 border-0 bg-transparent p-0">
            {TABS.map(({ key, labelKey }) => (
              <TabsTrigger
                key={key}
                value={key}
                className="rounded-lg border-b-0 px-3 py-1.5 text-xs data-[state=active]:bg-primary data-[state=active]:text-primary-foreground data-[state=inactive]:bg-muted data-[state=inactive]:text-muted-foreground"
              >
                {t(labelKey)}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        {tab === 'overview' && dev && (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <OperationalMetric label={t('ops.outcomeMetrics.verified')} value={String(dev.verified_outcome_count)} />
            <OperationalMetric label={t('ops.outcomeMetrics.pending')} value={dev.pending_outcome_count == null ? '—' : String(dev.pending_outcome_count)} />
            <OperationalMetric
              label={t('ops.outcomeMetrics.succeeded')}
              value={String(dev.succeeded)}
              detail={`${t('ops.outcomeMetrics.failed')}: ${dev.failed}`}
            />
            <OperationalMetric
              label={t('ops.outcomeMetrics.rate')}
              value={dev.verified_success_rate == null ? '—' : `${Math.round(dev.verified_success_rate * 100)}%`}
              detail={t('ops.outcomeMetrics.denominator', { count: dev.verified_outcome_count })}
            />
          </div>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
        {metricsLoading && !metrics ? (
          <LoadingState label={t('explore.loading')} />
        ) : metricsError ? (
          <ErrorState onRetry={refetchMetrics} />
        ) : tab === 'learning' ? (
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>{t('ops.outcomeMetrics.syntheticCaution')}</p>
            {metrics?.limitations?.map((line) => <p key={line}>{line}</p>)}
            {metrics?.as_of && <time dir="ltr" className="text-xs">{metrics.as_of}</time>}
          </div>
        ) : tab === 'overview' ? (
          <div className="space-y-4">
            {metrics?.synthetic && <p className="text-xs font-semibold text-chart-warning">{t('ops.simulation.label')}</p>}
            {dev && (
              <dl className="flex flex-wrap gap-2">
                {Object.entries(dev.case_counts ?? {}).map(([state, count]) => (
                  <div key={state} className="rounded-lg border border-border px-3 py-2">
                    <dt className="text-xs text-muted-foreground">{t(`ops.states.${state}`)}</dt>
                    <dd className="tabular-nums font-semibold" dir="ltr">{count}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        ) : showQueue ? (
          queueError ? (
            <ErrorState onRetry={refetchQueue} />
          ) : queueLoading && !queue ? (
            <LoadingState label={t('ops.loading')} />
          ) : (
            <>
              <QueueCasesTable
                cases={page.items}
                refreshing={queueRefreshing}
                emptyTitle={t('intake.emptyTitle')}
                emptyDescription={t('intake.emptyDescription')}
                actions={{
                  onOpen: () => undefined,
                  onCopyId: (row) => void navigator.clipboard?.writeText(row.caseId),
                }}
              />
              <div className="mt-4">
                <CursorPagination
                  total={page.total}
                  limit={limit}
                  cursorStart={pager.offset}
                  nextCursor={page.nextCursor}
                  prevCursor={pager.hasPrevious ? 'visited-page' : null}
                  onNext={() => pager.next(page.nextCursor, limit)}
                  onPrev={() => pager.previous(limit)}
                  onLimitChange={(n) => { setLimit(n); pager.reset() }}
                />
              </div>
            </>
          )
        ) : null}
      </div>
    </div>
  )
}
