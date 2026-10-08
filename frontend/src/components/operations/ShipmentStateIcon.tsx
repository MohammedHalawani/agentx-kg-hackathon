import type { OperationalShipmentStatus } from '@/contracts/operations'
import { OPERATIONAL_STATUS_VISUAL } from '@/lib/operationalStates'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { cn } from '@/lib/cn'

export function ShipmentStateIcon({
  status,
  size = 16,
  className,
  showLabel = false,
}: {
  status: OperationalShipmentStatus
  size?: number
  className?: string
  showLabel?: boolean
}) {
  const { t } = useLanguage()
  const { Icon, token, labelKey } = OPERATIONAL_STATUS_VISUAL[status]
  return (
    <span className={cn('inline-flex items-center gap-1', className)} title={t(labelKey)}>
      <Icon size={size} style={{ color: `var(${token})` }} aria-hidden="true" />
      {showLabel && <span className="text-xs">{t(labelKey)}</span>}
      <span className="sr-only">{t(labelKey)}</span>
    </span>
  )
}
