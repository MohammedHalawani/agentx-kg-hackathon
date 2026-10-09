import { RefreshCw, SlidersHorizontal } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { IntakeFilters } from '@/contracts/operations'
import { FilterField } from './FilterBar'
import { SearchInput } from './SearchInput'
import { DateRangeSelector } from './DateRangeSelector'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { operationalLabelKey } from '@/lib/operationalStates'
import { cn } from '@/lib/cn'

export function IntakeToolbar({
  filters,
  operationalStatus,
  operationalChoices,
  cities,
  causes,
  workflowChoices,
  onFiltersChange,
  onOperationalStatusChange,
  onTimePresetChange,
  customFrom,
  customTo,
  onCustomFrom,
  onCustomTo,
  limit,
  onLimitChange,
  onRefresh,
  refreshing,
}: {
  filters: IntakeFilters
  operationalStatus: string
  operationalChoices: string[]
  cities: string[]
  causes: string[]
  workflowChoices: string[]
  onFiltersChange: (patch: Partial<IntakeFilters>) => void
  onOperationalStatusChange: (value: string) => void
  onTimePresetChange: (preset: IntakeFilters['timePreset']) => void
  customFrom: string
  customTo: string
  onCustomFrom: (v: string) => void
  onCustomTo: (v: string) => void
  limit: number
  onLimitChange: (n: number) => void
  onRefresh: () => void
  refreshing?: boolean
}) {
  const { t, rootCauseLabel } = useLanguage()
  const selectClass = 'h-8 w-full min-w-[7rem] rounded-md border border-border bg-card px-2 text-xs'

  return (
    <div className="space-y-3 rounded-xl border border-border bg-card/50 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <div className="min-w-[12rem] flex-1">
          <SearchInput
            value={filters.search}
            onChange={(search) => onFiltersChange({ search })}
            placeholder={t('ops.intake.search')}
          />
        </div>
        <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={refreshing} className="gap-1.5">
          <RefreshCw size={14} className={cn(refreshing && 'animate-spin')} />
          {t('ops.table.refresh')}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={<Button type="button" variant="outline" size="sm" className="gap-1.5" aria-label={t('ops.table.viewOptions')} />}
          >
            <SlidersHorizontal size={14} />
            {t('ops.table.viewOptions')}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-40">
            <DropdownMenuLabel>{t('ops.pagination.pageSize')}</DropdownMenuLabel>
            {[25, 50, 100].map((n) => (
              <DropdownMenuItem key={n} onClick={() => onLimitChange(n)}>
                {n}
                {limit === n ? ' ✓' : ''}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <FilterField label={t('ops.filters.operational_status')}>
          <select value={operationalStatus} onChange={(e) => onOperationalStatusChange(e.target.value)} className={selectClass}>
            <option value="all">{t('ops.filters.all')}</option>
            {operationalChoices.map((status) => (
              <option key={status} value={status}>{t(operationalLabelKey(status))}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label={t('ops.filters.workflow')}>
          <select
            value={filters.status}
            onChange={(e) => onFiltersChange({ status: e.target.value as IntakeFilters['status'] })}
            className={selectClass}
          >
            <option value="all">{t('ops.filters.all')}</option>
            {workflowChoices.map((s) => (
              <option key={s} value={s}>{t(`ops.states.${s}`)}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label={t('ops.filters.priority')}>
          <select
            value={filters.priority}
            onChange={(e) => onFiltersChange({ priority: e.target.value as IntakeFilters['priority'] })}
            className={selectClass}
          >
            <option value="all">{t('ops.filters.all')}</option>
            <option value="high">{t('ops.priority.high')}</option>
            <option value="medium">{t('ops.priority.medium')}</option>
            <option value="low">{t('ops.priority.low')}</option>
          </select>
        </FilterField>
        <FilterField label={t('ops.filters.city')}>
          <select value={filters.city} onChange={(e) => onFiltersChange({ city: e.target.value })} className={selectClass}>
            <option value="all">{t('ops.filters.all')}</option>
            {cities.map((city) => (
              <option key={city} value={city}>{t(`cities.${city}`)}</option>
            ))}
          </select>
        </FilterField>
        <FilterField label={t('ops.filters.cause')}>
          <select value={filters.cause} onChange={(e) => onFiltersChange({ cause: e.target.value })} className={selectClass}>
            <option value="all">{t('ops.filters.all')}</option>
            {causes.map((cause) => (
              <option key={cause} value={cause}>{rootCauseLabel(cause)}</option>
            ))}
          </select>
        </FilterField>
        <DateRangeSelector value={filters.timePreset} onChange={onTimePresetChange} />
      </div>
      {filters.timePreset === 'custom' && (
        <div className="flex flex-wrap gap-2 text-xs">
          <label>{t('ops.filters.from')} <input type="date" value={customFrom} onChange={(e) => onCustomFrom(e.target.value)} className="rounded-md border border-border bg-card p-1" /></label>
          <label>{t('ops.filters.to')} <input type="date" value={customTo} onChange={(e) => onCustomTo(e.target.value)} className="rounded-md border border-border bg-card p-1" /></label>
        </div>
      )}
    </div>
  )
}
