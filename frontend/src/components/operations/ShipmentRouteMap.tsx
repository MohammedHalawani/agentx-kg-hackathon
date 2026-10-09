import { useEffect, useMemo, useState } from 'react'
import { Layers } from 'lucide-react'
import type { InspectStage, RouteLayerKey, ShipmentDetail } from '@/contracts/caseDetail'
import type { ExploreShipment } from '@/types/explore'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { ExploreMap } from '@/components/views/ExploreMap'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const LAYERS: RouteLayerKey[] = ['expected_route', 'actual_route', 'vehicle_path', 'custody_points', 'hub_stops', 'delivery_attempts', 'traffic']
const COMPACT_INLINE: RouteLayerKey[] = ['expected_route', 'custody_points', 'vehicle_path']
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

function LayerSwatch({ layerKey, on }: { layerKey: RouteLayerKey; on: boolean }) {
  return <span aria-hidden="true" className={`inline-block ${SWATCH[layerKey].includes('size-') ? '' : 'w-4'} ${SWATCH[layerKey]} ${on ? '' : 'opacity-50'}`} />
}

export function ShipmentRouteMap({ detail, shipment, onSelect = () => undefined, stage, highlightedIds, compact = false }: { detail: ShipmentDetail; shipment?: ExploreShipment; onSelect?: (s: ExploreShipment) => void; stage?: InspectStage; highlightedIds?: readonly string[]; compact?: boolean }) {
  const { t, isArabic } = useLanguage()
  const [visible, setVisible] = useState<RouteLayerKey[]>(['expected_route', 'custody_points'])
  useEffect(() => { setVisible(stageLayers(stage).filter(key => !!detail.route_layers?.layers[key]?.length)) }, [stage, detail.route_layers])
  const mapped = visible.flatMap(key => (detail.route_layers?.layers[key] ?? []).flatMap(p => 'points' in p ? p.points : [p])).some(p => highlightedIds?.includes(p.evidence_id ?? p.entity_id ?? ''))
  const toggle = (key: RouteLayerKey, on: boolean) => {
    if (!detail.route_layers?.layers[key]?.length) return
    setVisible(prev => (on ? [...new Set([...prev, key])] : prev.filter(k => k !== key)))
  }
  const inlineKeys = useMemo(() => (compact ? COMPACT_INLINE : LAYERS), [compact])
  const menuKeys = useMemo(() => (compact ? LAYERS.filter(k => !COMPACT_INLINE.includes(k)) : []), [compact])
  return <div className={`flex h-full flex-col ${compact ? 'min-h-0' : 'min-h-96'}`}>
    <div className={`flex items-center gap-1 border-b border-border bg-card ${compact ? 'px-2 py-1' : 'flex-wrap gap-y-2 p-2'}`} dir={isArabic ? 'rtl' : 'ltr'} role="group" aria-label={t('explore.layers')}>
      <div className="inline-flex shrink-0 rounded-lg border border-border bg-muted/30 p-0.5">
        {inlineKeys.map(key => {
          const available = !!detail.route_layers?.layers[key]?.length
          const on = visible.includes(key)
          return (
            <Button
              key={key}
              type="button"
              size="xs"
              variant={on ? 'secondary' : 'ghost'}
              disabled={!available}
              aria-pressed={on}
              title={t(`ops.layers.${key}`)}
              onClick={() => toggle(key, !on)}
              className={`gap-1 font-normal ${compact ? 'text-[10px]' : 'text-xs'}`}
            >
              <LayerSwatch layerKey={key} on={on} />
              <span className="max-w-[5.5rem] truncate">{t(`ops.layers.${key}`)}</span>
            </Button>
          )
        })}
      </div>
      {!!menuKeys.length && (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                type="button"
                size="xs"
                variant="outline"
                className="gap-1 text-[10px] font-normal"
                aria-label={t('explore.moreLayers')}
              />
            }
          >
            <Layers size={12} aria-hidden="true" />
            {t('explore.moreLayers')}
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="max-h-64 overflow-auto">
            {menuKeys.map(key => {
              const available = !!detail.route_layers?.layers[key]?.length
              const on = visible.includes(key)
              return (
                <DropdownMenuCheckboxItem
                  key={key}
                  disabled={!available}
                  checked={on}
                  onCheckedChange={(checked) => toggle(key, checked === true)}
                >
                  <LayerSwatch layerKey={key} on={on} />
                  {t(`ops.layers.${key}`)}
                </DropdownMenuCheckboxItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
    {!!stage && !!highlightedIds?.length && !mapped && <p className="bg-card px-3 py-0.5 text-[10px] text-muted-foreground">{t('ops.layers.contextOnly')}</p>}
    <div className={`flex-1 ${compact ? 'min-h-0' : 'min-h-80'}`} dir="ltr"><ExploreMap shipments={shipment ? [shipment] : []} selected={shipment ?? null} onSelect={onSelect} layers={detail.route_layers?.layers} visibleLayers={visible} highlightedIds={highlightedIds} /></div>
  </div>
}
