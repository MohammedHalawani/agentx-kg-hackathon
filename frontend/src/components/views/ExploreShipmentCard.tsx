import { useLanguage } from '@/components/i18n/LanguageProvider'
import { shipmentVisualState, type ExploreShipment } from '../../types/explore'
import { SHIPMENT_STATE_STYLE } from '../../lib/shipmentStyles'
import { CaseWorkflowBadge, OperationalStatusBadge } from '@/components/operations/StatusBadge'

export function RiskWatch({ shipment }: { shipment: ExploreShipment }) {
  const { t } = useLanguage()
  if (!shipment.risk_watch) return null
  return <span data-testid="risk-watch" title={t('explore.riskWatchHint', { at: shipment.risk_watch.latest_estimate_at ?? '', promise: shipment.risk_watch.promise_at ?? '' })}
    className="rounded-md border border-chart-warning/60 bg-chart-warning/10 px-1.5 py-0.5 text-[11px]">{t('explore.riskWatch')}</span>
}

export function ShipmentStatus({ shipment }: { shipment: ExploreShipment }) {
  const status = <ShipmentStatusInner shipment={shipment} />
  return shipment.risk_watch ? <span className="inline-flex flex-wrap items-center gap-1.5">{status}<RiskWatch shipment={shipment} /></span> : status
}

function ShipmentStatusInner({ shipment }: { shipment: ExploreShipment }) {
  const { t, rootCauseLabel } = useLanguage()
  const state = shipmentVisualState(shipment)
  const { Icon, className } = SHIPMENT_STATE_STYLE[state]
  if (shipment.operational_status) return <span className="inline-flex flex-wrap items-center gap-1.5"><OperationalStatusBadge status={shipment.operational_status} /><span className="text-xs text-muted-foreground" dir="auto">{t(`explore.statuses.${shipment.status}`) === `explore.statuses.${shipment.status}` ? shipment.status : t(`explore.statuses.${shipment.status}`)}</span>{shipment.operational_status === 'NEEDS_ATTENTION' && <span className="text-xs" dir="auto">{shipment.root_causes.map(rootCauseLabel).join(' · ')}</span>}</span>
  return <span className="inline-flex items-center gap-1.5 text-xs"><Icon size={14} className={className} aria-hidden="true" />{t(`explore.states.${state}`)} <span dir="auto" className="text-muted-foreground">({t(`explore.statuses.${shipment.status}`) === `explore.statuses.${shipment.status}` ? shipment.status : t(`explore.statuses.${shipment.status}`)})</span></span>
}

export function ExploreShipmentCard({ shipment, onOpenCase, actionLabel }: { shipment: ExploreShipment; onOpenCase?: (shipment: ExploreShipment) => void; actionLabel?: string }) {
  const { t, rootCauseLabel, isArabic } = useLanguage()
  const fields = [
    [t('explore.priority'), shipment.priority ? t(`explore.priorities.${shipment.priority}`) : t('explore.unknown')],
    [t('explore.rootCause'), shipment.root_causes.map(rootCauseLabel).join(' · ') || t('explore.unknown')],
    [t('explore.origin'), shipment.origin?.full || shipment.origin?.city || t('explore.unknown')],
    [t('explore.destination'), shipment.destinations.map(p => p.full || p.city).filter(Boolean).join(' · ') || shipment.city || t('explore.unknown')],
    [t('explore.lastEvent'), shipment.last_event ? `${t(`explore.events.${shipment.last_event.event_type}`) === `explore.events.${shipment.last_event.event_type}` ? shipment.last_event.event_type : t(`explore.events.${shipment.last_event.event_type}`)} · ${shipment.last_event.timestamp ?? t('explore.unknown')}` : t('explore.unknown')],
  ]
  return (
    <section aria-label={t('explore.shipmentDetails')} dir={isArabic ? 'rtl' : 'ltr'} className="space-y-3 rounded-xl border border-border bg-card p-3 text-sm">
      <h3 className="font-mono font-semibold" dir="ltr">{shipment.shipment_id}</h3>
      <div className="flex flex-wrap items-center gap-2">
        <ShipmentStatus shipment={shipment} />
        {shipment.workflow_state && <CaseWorkflowBadge state={shipment.workflow_state} />}
      </div>
      <dl className="space-y-2 text-xs">
        {fields.map(([label, value]) => <div key={label}><dt className="text-muted-foreground">{label}</dt><dd dir="auto" className="mt-0.5 break-words">{value}</dd></div>)}
      </dl>
      {onOpenCase && <button onClick={() => onOpenCase(shipment)} className="w-full rounded-lg bg-primary px-3 py-2 text-sm font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring">{actionLabel ?? t('explore.openCase')}</button>}
    </section>
  )
}
