import { useFetch } from '@/hooks/useFetch'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { OperationalMetric } from '@/components/operations/OperationalMetric'
import { ErrorState } from '@/components/operations/ErrorState'
import { LoadingState } from '@/components/operations/LoadingState'

interface DecisionMetrics { case_counts?: Record<string, number>; verified_outcome_count: number; succeeded: number; failed: number; pending_outcome_count?: number; verified_success_rate: number | null; denominator: string }
interface DecisionsData { as_of: string; synthetic: boolean; development: DecisionMetrics; history: DecisionMetrics; limitations?: string[] }
export function OperationsDecisionsView() {
  const { data, loading, error, refetch } = useFetch<DecisionsData>('/decisions')
  const { t, isArabic } = useLanguage()
  return <div className="h-full overflow-y-auto p-4 sm:p-6" dir={isArabic ? 'rtl' : 'ltr'}>
    <h2 className="font-display text-xl font-bold">{t('nav.decisions')}</h2>
    <p className="my-3 text-sm text-muted-foreground">{t('ops.outcomeMetrics.explanation')}</p>
    {loading ? <LoadingState label={t('explore.loading')} /> : error ? <ErrorState onRetry={refetch} /> : data && <>
      {data.synthetic && <p className="mb-3 text-xs font-semibold text-chart-warning">{t('ops.simulation.label')}</p>}
      {(['development', 'history'] as const).map(split => {
        const metrics = data[split]
        return <section key={split} className="mb-6 space-y-3"><h3 className="font-semibold">{t(`ops.outcomeMetrics.${split}`)}</h3><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <OperationalMetric label={t('ops.outcomeMetrics.verified')} value={String(metrics.verified_outcome_count)} />
          <OperationalMetric label={t('ops.outcomeMetrics.pending')} value={metrics.pending_outcome_count == null ? '—' : String(metrics.pending_outcome_count)} />
          <OperationalMetric label={t('ops.outcomeMetrics.succeeded')} value={String(metrics.succeeded)} detail={`${t('ops.outcomeMetrics.failed')}: ${metrics.failed}`} />
          <OperationalMetric label={t('ops.outcomeMetrics.rate')} value={metrics.verified_success_rate == null ? '—' : `${Math.round(metrics.verified_success_rate * 100)}%`} detail={t('ops.outcomeMetrics.denominator', { count: metrics.verified_outcome_count })} />
        </div><dl className="flex flex-wrap gap-3">{Object.entries(metrics.case_counts ?? {}).map(([state, count]) => <div key={state} className="rounded-lg border border-border p-3"><dt className="text-xs text-muted-foreground">{t(`ops.states.${state}`)}</dt><dd className="tabular-nums" dir="ltr">{count}</dd></div>)}</dl></section>
      })}
      <p className="text-xs text-muted-foreground">{t('ops.outcomeMetrics.syntheticCaution')}</p>
      <time className="text-xs text-muted-foreground" dir="ltr">{data.as_of}</time>
    </>}
  </div>
}
