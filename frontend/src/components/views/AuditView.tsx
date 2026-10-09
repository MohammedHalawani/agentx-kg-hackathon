import { useCursorPage } from '@/hooks/useCursorPage'
import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { adaptAudit, dateBounds, pageQuery, type ApiAuditEvent } from '@/adapters/operationsApi'
import type { TimeRangePreset } from '@/contracts/operations'
import { FilterBar, FilterField } from '@/components/operations/FilterBar'
import { SearchInput } from '@/components/operations/SearchInput'
import { DateRangeSelector } from '@/components/operations/DateRangeSelector'
import { AuditLedgerTable } from '@/components/operations/AuditLedgerTable'
import { CursorPagination } from '@/components/operations/Pagination'
import { EmptyState } from '@/components/operations/EmptyState'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'

export function AuditView({ onOpenCase }: { onOpenCase?: (shipmentId: string, caseId: string) => void }) {
  const { t, isArabic } = useLanguage()
  const [filters, setFilters] = useState({ search: '', event_type: 'all', actor: '', model: '', workflow_state: 'all', shipment_id: '', case_id: '' })
  const [time, setTime] = useState<TimeRangePreset | 'all'>('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [limit, setLimit] = useState(25)
  const pager = useCursorPage()
  const cursor = pager.cursor
  const offset = pager.offset
  const [snapshot, setSnapshot] = useState<string | undefined>()
  const query = pageQuery({ ...filters, ...dateBounds(time, snapshot, from, to), limit, cursor })
  const { data, loading, error, refetch } = useOperationsPage<ApiAuditEvent>(`/audit?${query}`)
  const refreshing = loading && data != null
  const initialLoad = loading && !data
  const change = (key: keyof typeof filters, value: string) => { setFilters(f => ({ ...f, [key]: value })); pager.reset() }

  return (
    <div className="flex h-full flex-col overflow-hidden" dir={isArabic ? 'rtl' : 'ltr'}>
      <div className="shrink-0 space-y-3 border-b border-border px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <h2 className="font-display text-xl font-bold text-ink">{t('ops.audit.title')}</h2>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('ops.audit.subtitle')}</p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={refetch} disabled={refreshing} className="gap-1.5">
            <RefreshCw size={14} className={cn(refreshing && 'animate-spin')} />
            {t('ops.table.refresh')}
          </Button>
        </div>
        <FilterBar>
          <SearchInput value={filters.search} onChange={v => change('search', v)} placeholder={t('ops.audit.search')} />
          <FilterField label={t('ops.audit.eventType')}><select value={filters.event_type} onChange={e => change('event_type', e.target.value)} className="rounded-md border border-border bg-card p-1.5 text-xs"><option value="all">{t('ops.filters.all')}</option>{(data?.metadata?.filter_choices?.event_type ?? data?.metadata?.filter_choices?.event_types ?? []).map(type => <option key={type} value={type}>{t(`ops.audit.events.${type}`)}</option>)}</select></FilterField>
          <FilterField label={t('ops.filters.workflow')}><select value={filters.workflow_state} onChange={e => change('workflow_state', e.target.value)} className="rounded-md border border-border bg-card p-1.5 text-xs"><option value="all">{t('ops.filters.all')}</option>{(data?.metadata?.filter_choices?.workflow_state ?? []).map(state => <option key={state} value={state}>{t(`ops.states.${state}`)}</option>)}</select></FilterField>
          {(['shipment_id', 'case_id', 'actor', 'model'] as const).map(key => <FilterField key={key} label={t(`ops.audit.${key}`)}><input value={filters[key]} onChange={e => change(key, e.target.value)} className="w-32 rounded-md border border-border bg-card p-1.5 text-xs" dir="auto" /></FilterField>)}
        </FilterBar>
        <DateRangeSelector value={time} onChange={v => { setTime(v); setSnapshot(data?.metadata?.as_of); pager.reset() }} />
        {time === 'custom' && <div className="flex flex-wrap gap-2 text-xs"><label>{t('ops.filters.from')} <input type="date" value={from} onChange={e => { setFrom(e.target.value); pager.reset() }} /></label><label>{t('ops.filters.to')} <input type="date" value={to} onChange={e => { setTo(e.target.value); pager.reset() }} /></label></div>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
        {initialLoad ? <LoadingState label={t('ops.audit.loading')} /> : error ? <ErrorState onRetry={refetch} /> : !data?.items.length ? <EmptyState title={t('ops.audit.emptyTitle')} description={t('ops.audit.emptyDescription')} /> : <>
          <AuditLedgerTable events={data.items.map(adaptAudit)} onOpenCase={onOpenCase} refreshing={refreshing} />
          <div className="mt-4"><CursorPagination total={data.filtered_total} limit={limit} cursorStart={offset} nextCursor={data.next_cursor} prevCursor={pager.hasPrevious ? 'visited-page' : null} onNext={() => pager.next(data.next_cursor, limit)} onPrev={() => pager.previous(limit)} onLimitChange={n => { setLimit(n); pager.reset() }} /></div>
        </>}
      </div>
    </div>
  )
}
