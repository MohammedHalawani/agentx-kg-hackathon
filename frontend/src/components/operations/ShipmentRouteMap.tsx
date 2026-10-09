import { useEffect, useState } from 'react'
import type { InspectStage, RouteLayerKey, ShipmentDetail } from '@/contracts/caseDetail'
import type { ExploreShipment } from '@/types/explore'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ExploreMap } from '@/components/views/ExploreMap'

const LAYERS: RouteLayerKey[] = ['expected_route', 'actual_route', 'vehicle_path', 'custody_points', 'hub_stops', 'delivery_attempts', 'traffic']
// Swatches mirror ExploreMap's line styles so the legend is the toggle.
const SWATCH: Record<RouteLayerKey, string> = {
  expected_route: 'border-t-2 border-dashed border-chart-blue',
  actual_route: 'border-t-2 border-chart-good',
  vehicle_path: 'border-t-2 border-dotted border-chart-orange',
  custody_points: 'size-2 rounded-full border-2 border-muted-foreground',
  hub_stops: 'size-2 rounded-[2px] border-2 border-muted-foreground',
  delivery_attempts: 'size-2 rounded-full border-2 border-primary',
  traffic: 'size-2 rounded-full border-2 border-chart-warning',
}

function stageLayers(stage?: InspectStage): RouteLayerKey[] {
  if (stage === 'classify') return ['expected_route', 'actual_route', 'custody_points', 'traffic']
  if (stage && ['review', 'writeback', 'escalate', 'outcome'].includes(stage)) return ['expected_route', 'custody_points', 'delivery_attempts']
  return ['expected_route', 'custody_points']
}

export function ShipmentRouteMap({ detail, shipment, onSelect = () => undefined, stage, highlightedIds, compact = false }: { detail: ShipmentDetail; shipment?: ExploreShipment; onSelect?: (s: ExploreShipment) => void; stage?: InspectStage; highlightedIds?: readonly string[]; compact?: boolean }) {
  const { t, isArabic } = useLanguage()
  const [visible, setVisible] = useState<RouteLayerKey[]>(['expected_route', 'custody_points'])
  useEffect(() => { setVisible(stageLayers(stage).filter(key => !!detail.route_layers?.layers[key]?.length)) }, [stage, detail.route_layers])
  const mapped = visible.flatMap(key => (detail.route_layers?.layers[key] ?? []).flatMap(p => 'points' in p ? p.points : [p])).some(p => highlightedIds?.includes(p.evidence_id ?? p.entity_id ?? ''))
  return <div className={`flex h-full flex-col ${compact ? 'min-h-0' : 'min-h-96'}`}>
    <fieldset className={`flex gap-x-1.5 border-b border-border bg-card ${compact ? 'flex-nowrap overflow-x-auto px-2 py-1 text-[10px]' : 'flex-wrap gap-y-2 p-3 text-xs'}`} dir={isArabic ? 'rtl' : 'ltr'}>
      <legend className="sr-only">{t('explore.layers')}</legend>
      {LAYERS.map(key => {
        const available = !!detail.route_layers?.layers[key]?.length
        const on = visible.includes(key)
        return <label key={key} title={t(`ops.layers.${key}`)} className={`flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full border px-2 py-0.5 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ring ${!available ? 'cursor-not-allowed opacity-40' : on ? 'border-primary/40 bg-primary/5' : 'border-border text-muted-foreground'}`}>
          <input type="checkbox" className="sr-only" disabled={!available} checked={on} onChange={e => setVisible(prev => e.target.checked ? [...prev, key] : prev.filter(k => k !== key))} />
          <span aria-hidden="true" className={`inline-block ${SWATCH[key].includes('size-') ? '' : 'w-4'} ${SWATCH[key]} ${on ? '' : 'opacity-50'}`} />
          {t(`ops.layers.${key}`)}
        </label>
      })}
    </fieldset>
    {!!stage && !!highlightedIds?.length && !mapped && <p className="bg-card px-3 py-0.5 text-[10px] text-muted-foreground">{t('ops.layers.contextOnly')}</p>}
    <div className={`flex-1 ${compact ? 'min-h-0' : 'min-h-80'}`} dir="ltr"><ExploreMap shipments={shipment ? [shipment] : []} selected={shipment ?? null} onSelect={onSelect} layers={detail.route_layers?.layers} visibleLayers={visible} highlightedIds={highlightedIds} /></div>
  </div>
}
