import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { CaseWorkflowState, OperationalShipmentStatus } from '@/contracts/operations'
import { CASE_WORKFLOW_VISUAL, OPERATIONAL_STATUS_VISUAL } from '@/lib/operationalStates'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'

export function OperationalStatusBadge({
  status,
  className,
}: {
  status: OperationalShipmentStatus
  className?: string
}) {
  const { t } = useLanguage()
  const visual = OPERATIONAL_STATUS_VISUAL[status]
  const { Icon } = visual
  const badge = (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-card px-2 py-0.5 text-xs font-medium text-foreground',
        className,
      )}
      style={{ borderColor: `color-mix(in oklab, var(${visual.token}) 35%, var(--color-border))` }}
    >
      <Icon size={14} className="shrink-0" style={{ color: `var(${visual.token})` }} aria-hidden="true" />
      <span className="truncate">{t(visual.labelKey)}</span>
    </span>
  )
  if (!visual.hintKey) return badge
  return (
    <Tooltip>
      <TooltipTrigger render={badge} />
      <TooltipContent side="top" className="max-w-xs">{t(visual.hintKey)}</TooltipContent>
    </Tooltip>
  )
}

export function CaseWorkflowBadge({ state, className }: { state: CaseWorkflowState; className?: string }) {
  const { t } = useLanguage()
  const visual = CASE_WORKFLOW_VISUAL[state]
  const { Icon } = visual
  const badge = (
    <span
      className={cn(
        'inline-flex max-w-full items-center gap-1.5 rounded-md border border-border bg-card px-2 py-0.5 text-xs font-medium',
        className,
      )}
    >
      <Icon size={14} className="shrink-0" style={{ color: `var(${visual.token})` }} aria-hidden="true" />
      <span className="truncate">{t(visual.labelKey)}</span>
    </span>
  )
  if (!visual.hintKey) return badge
  return (
    <Tooltip>
      <TooltipTrigger render={badge} />
      <TooltipContent side="top" className="max-w-xs">{t(visual.hintKey)}</TooltipContent>
    </Tooltip>
  )
}
