import { FolderOpen } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { OperationsCase } from '@/contracts/operations'
import { CaseWorkflowBadge } from './StatusBadge'
import { PriorityBadge } from './PriorityBadge'
import { OperationalStatusBadge } from './StatusBadge'
import { cn } from '@/lib/cn'

export function CaseCard({
  caseRow,
  onSelect,
  selected,
}: {
  caseRow: OperationsCase
  onSelect: () => void
  selected?: boolean
}) {
  const { t, rootCauseLabel, isArabic } = useLanguage()
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        'group flex w-full items-center gap-3 rounded-xl border bg-card px-3 py-2.5 text-start transition-colors focus-visible:outline-2 focus-visible:outline-ring',
        selected ? 'border-primary bg-accent' : 'border-border hover:border-primary/35 hover:bg-accent hover:text-accent-foreground',
      )}
    >
      <span className="min-w-0 flex-1" dir={isArabic ? 'rtl' : undefined}>
        <span className="block truncate text-sm text-ink group-hover:text-accent-foreground" dir="auto">
          {caseRow.issueSummary}
        </span>
        <span className="mt-1 flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] text-muted-foreground group-hover:text-accent-foreground/80" dir="ltr">
            {caseRow.shipmentId}
          </span>
          {caseRow.category && (
            <span className="text-[11px] text-muted-foreground group-hover:text-accent-foreground/80" dir="auto">
              {rootCauseLabel(caseRow.category)}
            </span>
          )}
          {caseRow.city && <span className="text-[11px] text-muted-foreground" dir="auto">{caseRow.city}</span>}
        </span>
        <span className="mt-1.5 flex flex-wrap gap-1.5">
          <PriorityBadge priority={caseRow.priority} />
          <CaseWorkflowBadge state={caseRow.workflowState} />
          {caseRow.operationalStatus && <OperationalStatusBadge status={caseRow.operationalStatus} />}
        </span>
        {caseRow.durationLabel && (
          <span className="mt-1 block text-[11px] text-muted-foreground">{caseRow.durationLabel}</span>
        )}
      </span>
      <FolderOpen size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="sr-only">{t('explore.openCase')}</span>
    </button>
  )
}
