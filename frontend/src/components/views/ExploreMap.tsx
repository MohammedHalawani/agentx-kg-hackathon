import { useEffect, useMemo, useState } from 'react'
import { divIcon } from 'leaflet'
import { MapContainer, Marker, Polyline, TileLayer, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useTheme } from '../theme/ThemeProvider'
import { cssVar } from '../../lib/theme'
import { shipmentVisualState, type ExploreShipment } from '../../types/explore'
import { SHIPMENT_STATE_STYLE } from '../../lib/shipmentStyles'
import { OPERATIONAL_STATUS_VISUAL } from '@/lib/operationalStates'
import type { LayerPoint, RouteLayerKey, RouteLayers } from '@/contracts/caseDetail'

function ViewportBounds({ coordinates }: { coordinates: string }) {
  const map = useMap()
  useEffect(() => { map.invalidateSize(); map.fitBounds(JSON.parse(coordinates), { padding: [35, 35], maxZoom: 11, animate: false }) }, [map, coordinates])
  return null
}

export function ExploreMap({ shipments, selected, onSelect, layers, visibleLayers = [] }: { shipments: ExploreShipment[]; selected: ExploreShipment | null; onSelect: (shipment: ExploreShipment) => void; layers?: RouteLayers; visibleLayers?: RouteLayerKey[] }) {
  const { t } = useLanguage()
  const { resolvedTheme } = useTheme()
  const [addressGroup, setAddressGroup] = useState<ExploreShipment[]>([])
  const icons = useMemo(() => Object.fromEntries(Object.entries(SHIPMENT_STATE_STYLE).map(([state, style]) => [state, divIcon({
    className: '', iconSize: [28, 28], iconAnchor: [14, 14],
    html: `<span aria-hidden="true" style="display:grid;place-items:center;width:28px;height:28px;border:2px solid ${cssVar(style.token)};background:${cssVar('--color-card')};color:${cssVar(style.token)};border-radius:50%;font-size:18px;font-weight:bold;box-shadow:0 1px 4px #0003">${style.glyph}</span>`,
  })])),
  // CSS variable reads are external to React; theme changes must refresh Leaflet's icons.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [resolvedTheme])
  const operationalIcons = useMemo(() => Object.fromEntries(Object.entries(OPERATIONAL_STATUS_VISUAL).map(([status, visual]) => [status, divIcon({ className: '', iconSize: [30, 30], iconAnchor: [15, 15], html: `<span aria-hidden="true" style="display:grid;place-items:center;width:30px;height:30px;border:2px ${visual.pattern === 'solid' ? 'solid' : 'dashed'} ${cssVar(visual.token)};background:${cssVar('--color-card')};color:${cssVar(visual.token)};border-radius:50%;font-size:18px;font-weight:bold">${({ ON_TIME: '✓', NEEDS_ATTENTION: '?', SLA_RISK: '◷', CRITICAL: '!', UNRECONCILED_CUSTODY: '?', DELIVERY_DISPUTE: '⚖', ADDRESS_CONFLICT: '⌖', RECIPIENT_UNAVAILABLE: '⊘', HUB_DELAY: '↻', RESOLVED: '✓' } as Record<string, string>)[status]}</span>` })])),
  // Theme CSS variable reads must rebuild the Leaflet marker artwork.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [resolvedTheme])
  // Coordinates describe addresses / approximate warehouse origin, never a parcel's live GPS.
  const mappable = shipments.flatMap(shipment => {
    const point = shipment.destinations[0] ?? shipment.origin
    return point && Number.isFinite(point.lat) && Number.isFinite(point.lng) && Math.abs(point.lat) <= 90 && Math.abs(point.lng) <= 180 ? [{ shipment, point }] : []
  })
  const validPoint = (p: LayerPoint) => Number.isFinite(p.lat) && Number.isFinite(p.lng) && Math.abs(p.lat) <= 90 && Math.abs(p.lng) <= 180
  const pointsFor = (key: RouteLayerKey) => (layers?.[key] ?? []).flatMap(p => 'points' in p ? p.points : [p]).filter(validPoint)
  const layerPoints = visibleLayers.flatMap(pointsFor)
  if (!mappable.length && !layerPoints.length) return <div role="status" className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{t('explore.noCoordinates')}</div>
  const bounds = [...mappable.flatMap(({ shipment, point }) => [point, ...(shipment.origin ? [shipment.origin] : [])]), ...layerPoints].filter(validPoint).map(p => [p.lat, p.lng] as [number, number])
  const visibleStatuses = [...new Set(shipments.map(s => s.operational_status).filter(s => s != null))]
  const addressGroups = [...mappable.reduce<Map<string, typeof mappable>>((groups, row) => {
    const key = `${row.point.lat.toFixed(5)},${row.point.lng.toFixed(5)}`
    groups.set(key, [...(groups.get(key) ?? []), row]); return groups
  }, new Map()).entries()]
  const origin = selected?.origin
  return (
    <div className="relative h-full min-h-80" aria-label={t('explore.mapHint')}>
      <MapContainer bounds={bounds} boundsOptions={{ padding: [35, 35], maxZoom: 11 }} className="h-full w-full" scrollWheelZoom>
        <ViewportBounds coordinates={JSON.stringify(bounds)} />
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {addressGroups.map(([key, group]) => {
          const { shipment, point } = group[0]
          const multiple = group.length > 1
          const title = multiple ? t('explore.groupedAddresses', { count: group.length }) : `${shipment.shipment_id} · ${shipment.operational_status ? t(OPERATIONAL_STATUS_VISUAL[shipment.operational_status].labelKey) : t(`explore.states.${shipmentVisualState(shipment)}`)}`
          const icon = multiple ? divIcon({ className: '', iconSize: [34,34], iconAnchor: [17,17], html: `<span style="display:grid;place-items:center;width:34px;height:34px;border:2px solid ${cssVar('--color-primary')};background:${cssVar('--color-card')};color:${cssVar('--color-foreground')};border-radius:50%;font-weight:600">${group.length}</span>` }) : shipment.operational_status ? operationalIcons[shipment.operational_status] : icons[shipmentVisualState(shipment)]
          return <Marker key={key} position={[point.lat, point.lng]} icon={icon} title={title} alt={title} eventHandlers={{ click: () => multiple ? setAddressGroup(group.map(row => row.shipment)) : onSelect(shipment) }} />
        })}
        {visibleLayers.map(key => {
          const points = pointsFor(key)
          if (key === 'expected_route') return (layers?.expected_route ?? []).map((segment, i) => {
            const pts = ('points' in segment ? segment.points : [segment]).filter(validPoint)
            return pts.length > 1 ? <Polyline key={`${key}-${i}`} positions={pts.map(p => [p.lat, p.lng])} pathOptions={{ color: cssVar('--color-chart-blue'), weight: 3, dashArray: '5 6' }} /> : null
          })
          if (key === 'vehicle_path') return [...new Set(points.map(p => p.vehicle_id))].map(vehicle => {
            const pts = points.filter(p => p.vehicle_id === vehicle)
            return pts.length > 1 ? <Polyline key={vehicle ?? key} positions={pts.map(p => [p.lat, p.lng])} pathOptions={{ color: cssVar('--color-chart-orange'), weight: 3, dashArray: '2 6' }} /> : null
          })
          // Corroborated stops are discrete observations, never an interpolated parcel path.
          return points.map((p, i) => <Marker key={`${key}-${i}`} position={[p.lat, p.lng]} icon={icons.normal} title={`${t(`ops.layers.${key}`)} · ${p.entity_id ?? ''} · ${p.occurred_at ?? ''}`} alt={t(`ops.layers.${key}`)} />)
        })}
        {origin && <>
          <Marker position={[origin.lat, origin.lng]} icon={icons.normal} title={t(origin.approximate ? 'explore.originApproximate' : 'explore.origin')} alt={t('explore.origin')} />
        </>}
      </MapContainer>
      {!!addressGroup.length && <div className="absolute bottom-16 start-3 z-[450] max-h-56 w-64 max-w-[85%] space-y-2 overflow-auto rounded-xl border border-border bg-card p-3 shadow-lg"><div className="flex items-start justify-between gap-2"><p className="text-xs">{t('explore.groupedAddresses', { count: addressGroup.length })}</p><button type="button" onClick={() => setAddressGroup([])} className="rounded border border-border px-2" aria-label={t('explore.closeGroup')}>×</button></div>{addressGroup.map(s => <button key={s.shipment_id} type="button" onClick={() => onSelect(s)} className="block w-full rounded border border-border p-2 text-start font-mono text-xs" dir="ltr">{s.shipment_id}</button>)}</div>}
      {!!visibleStatuses.length && <div className="pointer-events-none absolute top-3 end-3 z-[400] max-w-[65%] rounded-lg border border-border bg-card/95 p-2 text-xs text-foreground" aria-label={t('explore.legend')}>
        {visibleStatuses.map(state => { const visual = OPERATIONAL_STATUS_VISUAL[state]; return <span key={state} className="me-3 inline-flex items-center gap-1"><visual.Icon size={14} style={{ color: cssVar(visual.token) }} aria-hidden="true" />{t(visual.labelKey)}</span> })}
      </div>}
      <p className="pointer-events-none absolute bottom-6 start-3 z-[400] max-w-[75%] rounded-lg border border-border bg-card/95 px-2 py-1 text-xs text-foreground">{t('ops.layers.vehicleDisclaimer')}</p>
    </div>
  )
}
