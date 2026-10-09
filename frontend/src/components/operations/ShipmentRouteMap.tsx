import { useEffect, useState } from 'react'
import type { PipelineStage, RouteLayerKey, ShipmentDetail } from '@/contracts/caseDetail'
import type { ExploreShipment } from '@/types/explore'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ExploreMap } from '@/components/views/ExploreMap'

const LAYERS: RouteLayerKey[] = ['expected_route', 'actual_route', 'vehicle_path', 'custody_points', 'hub_stops', 'delivery_attempts', 'traffic']
export function ShipmentRouteMap({ detail, shipment, onSelect = () => undefined, stage, highlightedIds, compact=false }: { detail: ShipmentDetail; shipment?: ExploreShipment; onSelect?: (s: ExploreShipment) => void; stage?:PipelineStage; highlightedIds?:readonly string[]; compact?:boolean }) {
  const { t, isArabic } = useLanguage()
  const [visible, setVisible] = useState<RouteLayerKey[]>(['expected_route', 'custody_points'])
  useEffect(()=>{ const candidates:RouteLayerKey[] = ['expected_route','custody_points',...(stage==='classify'?['actual_route','traffic'] as RouteLayerKey[]:[]),...(['review','writeback'].includes(stage ?? '')?['delivery_attempts'] as RouteLayerKey[]:[])]; setVisible(candidates.filter(key=>!!detail.route_layers?.layers[key]?.length)) },[stage, detail.route_layers])
  const mapped=visible.flatMap(key=>(detail.route_layers?.layers[key]??[]).flatMap(p=>'points' in p?p.points:[p])).some(p=>highlightedIds?.includes(p.evidence_id??p.entity_id??''))
  return <div className={`flex h-full flex-col ${compact?'min-h-0':'min-h-96'}`}>
    <fieldset className="flex flex-wrap gap-x-4 gap-y-2 rounded-t-xl border-b border-border bg-card p-3 text-xs" dir={isArabic ? 'rtl' : 'ltr'}>
      <legend className="sr-only">{t('explore.layers')}</legend>
      {LAYERS.map(key => <label key={key} className="flex items-center gap-2"><input type="checkbox" disabled={!detail.route_layers?.layers[key]?.length} checked={visible.includes(key)} onChange={e => setVisible(prev => e.target.checked ? [...prev, key] : prev.filter(k => k !== key))} />{t(`ops.layers.${key}`)}</label>)}
    </fieldset>
    {stage&&highlightedIds?.length&&!mapped&&<p className="bg-card px-3 py-1 text-[10px] text-muted-foreground">{t('ops.layers.contextOnly')}</p>}
    <div className={`flex-1 ${compact?'min-h-0':'min-h-80'}`} dir="ltr"><ExploreMap shipments={shipment ? [shipment] : []} selected={shipment ?? null} onSelect={onSelect} layers={detail.route_layers?.layers} visibleLayers={visible} highlightedIds={highlightedIds} /></div>
  </div>
}
