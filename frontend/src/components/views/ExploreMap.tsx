import { useMemo } from 'react'
import { divIcon } from 'leaflet'
import { MapContainer, Marker, Polyline, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useTheme } from '../theme/ThemeProvider'
import { cssVar } from '../../lib/theme'
import { shipmentVisualState, type ExploreShipment } from '../../types/explore'
import { SHIPMENT_STATE_STYLE } from '../../lib/shipmentStyles'

export function ExploreMap({ shipments, selected, onSelect }: { shipments: ExploreShipment[]; selected: ExploreShipment | null; onSelect: (shipment: ExploreShipment) => void }) {
  const { t } = useLanguage()
  const { resolvedTheme } = useTheme()
  const icons = useMemo(() => Object.fromEntries(Object.entries(SHIPMENT_STATE_STYLE).map(([state, style]) => [state, divIcon({
    className: '', iconSize: [28, 28], iconAnchor: [14, 14],
    html: `<span aria-hidden="true" style="display:grid;place-items:center;width:28px;height:28px;border:2px solid ${cssVar(style.token)};background:${cssVar('--color-card')};color:${cssVar(style.token)};border-radius:50%;font-size:18px;font-weight:bold;box-shadow:0 1px 4px #0003">${style.glyph}</span>`,
  })])),
  // CSS variable reads are external to React; theme changes must refresh Leaflet's icons.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  [resolvedTheme])
  // Coordinates describe addresses / approximate warehouse origin, never a parcel's live GPS.
  const mappable = shipments.flatMap(shipment => {
    const point = shipment.destinations[0] ?? shipment.origin
    return point && Number.isFinite(point.lat) && Number.isFinite(point.lng) ? [{ shipment, point }] : []
  })
  if (!mappable.length) return <div role="status" className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{t('explore.noCoordinates')}</div>
  const bounds = mappable.flatMap(({ shipment, point }) => [point, ...(shipment.origin ? [shipment.origin] : [])]).map(p => [p.lat, p.lng] as [number, number])
  const origin = selected?.origin
  const destination = selected?.destinations[0]
  return (
    <div className="relative h-full min-h-80" aria-label={t('explore.mapHint')}>
      <MapContainer bounds={bounds} boundsOptions={{ padding: [35, 35], maxZoom: 11 }} className="h-full w-full" scrollWheelZoom>
        <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
        {mappable.map(({ shipment, point }) => <Marker key={shipment.shipment_id} position={[point.lat, point.lng]} icon={icons[shipmentVisualState(shipment)]} title={`${shipment.shipment_id} · ${t(`explore.states.${shipmentVisualState(shipment)}`)}`} alt={shipment.shipment_id} eventHandlers={{ click: () => onSelect(shipment) }} />)}
        {origin && destination && <>
          <Polyline positions={[[origin.lat, origin.lng], [destination.lat, destination.lng]]} pathOptions={{ color: cssVar('--color-chart-blue'), weight: 2, dashArray: '5 6' }} />
          <Marker position={[origin.lat, origin.lng]} icon={icons.normal} title={t('explore.originApproximate')} alt={t('explore.originApproximate')} />
        </>}
      </MapContainer>
      <div className="pointer-events-none absolute top-3 end-3 z-[400] max-w-[65%] rounded-lg border border-border bg-card/95 p-2 text-xs text-foreground" aria-label={t('explore.legend')}>
        {Object.entries(SHIPMENT_STATE_STYLE).map(([state, style]) => <span key={state} className="me-3 inline-flex items-center gap-1"><style.Icon size={14} className={style.className} aria-hidden="true" />{t(`explore.states.${state}`)}</span>)}
      </div>
      <p className="pointer-events-none absolute bottom-6 start-3 z-[400] max-w-[75%] rounded-lg border border-border bg-card/95 px-2 py-1 text-xs text-foreground">{origin && destination ? t('explore.expectedConnection') : t('explore.addressLocations')}</p>
    </div>
  )
}
