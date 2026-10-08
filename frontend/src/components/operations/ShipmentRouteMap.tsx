import { useState } from 'react'
import type { RouteLayerKey, ShipmentDetail } from '@/contracts/caseDetail'
import type { ExploreShipment } from '@/types/explore'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ExploreMap } from '@/components/views/ExploreMap'

const LAYERS: RouteLayerKey[] = ['expected_route', 'actual_route', 'vehicle_path', 'custody_points', 'hub_stops', 'delivery_attempts']
export function ShipmentRouteMap({ detail, shipment, onSelect = () => undefined }: { detail: ShipmentDetail; shipment?: ExploreShipment; onSelect?: (s: ExploreShipment) => void }) {
  const { t, isArabic } = useLanguage()
  const [visible, setVisible] = useState<RouteLayerKey[]>(['expected_route', 'custody_points'])
  return <div className="flex h-full min-h-96 flex-col">
    <fieldset className="flex flex-wrap gap-x-4 gap-y-2 rounded-t-xl border-b border-border bg-card p-3 text-xs" dir={isArabic ? 'rtl' : 'ltr'}>
      <legend className="sr-only">{t('explore.layers')}</legend>
      {LAYERS.map(key => <label key={key} className="flex items-center gap-2"><input type="checkbox" checked={visible.includes(key)} onChange={e => setVisible(prev => e.target.checked ? [...prev, key] : prev.filter(k => k !== key))} />{t(`ops.layers.${key}`)}</label>)}
    </fieldset>
    <div className="min-h-80 flex-1" dir="ltr"><ExploreMap shipments={shipment ? [shipment] : []} selected={shipment ?? null} onSelect={onSelect} layers={detail.route_layers?.layers} visibleLayers={visible} /></div>
  </div>
}
