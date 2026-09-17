import 'leaflet/dist/leaflet.css'
import { useMemo } from 'react'
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { cssVar } from '../../lib/theme'
import type { RoutePoint } from '../../types/agent'
import { useTheme } from '../theme/ThemeProvider'

const STYLE_COLORS: Record<RoutePoint['kind'], string> = {
  warehouse: '--color-chart-blue',
  delivery: '--color-chart-orange',
  home: '--color-chart-aqua',
}

const KIND_ORDER: RoutePoint['kind'][] = ['warehouse', 'delivery', 'home']

const KIND_LABEL_KEYS: Record<RoutePoint['kind'], string> = {
  warehouse: 'intake.map.warehouse',
  delivery: 'intake.map.delivery',
  home: 'intake.map.home',
}

export function ShipmentMap({ origin, points }: { origin: RoutePoint | null; points: RoutePoint[] }) {
  const { t } = useLanguage()
  const { resolvedTheme } = useTheme()
  const pinColors = useMemo(
    () => ({
      line: cssVar('--color-chart-blue'),
      warehouse: cssVar(STYLE_COLORS.warehouse),
      delivery: cssVar(STYLE_COLORS.delivery),
      home: cssVar(STYLE_COLORS.home),
    }),
    [resolvedTheme],
  )

  const all = [...(origin ? [origin] : []), ...points]
  if (!all.length) {
    return (
      <div className="grid h-full place-items-center p-4 text-center text-xs text-muted-foreground">
        {t('intake.map.empty')}
      </div>
    )
  }

  // Fit to everything rather than centring on one pin: the distance between origin and
  // destination is part of what the map is being read for.
  const lats = all.map((p) => p.lat)
  const lngs = all.map((p) => p.lng)
  const bounds: LatLngBoundsExpression = [
    [Math.min(...lats), Math.min(...lngs)],
    [Math.max(...lats), Math.max(...lngs)],
  ]
  // A straight geodesic, not a driving route - there is no routing service wired up, and a
  // line that looks like a road would imply knowledge the app does not have.
  const line: LatLngExpression[] = origin && points.length
    ? [[origin.lat, origin.lng], [points[0].lat, points[0].lng]]
    : []

  const present = KIND_ORDER.filter((k) => all.some((p) => p.kind === k))

  return (
    <div className="relative h-full w-full">
      <MapContainer
        bounds={bounds}
        boundsOptions={{ padding: [28, 28], maxZoom: 11 }}
        scrollWheelZoom={false}
        className="h-full w-full"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {line.length > 0 && (
          <Polyline positions={line} pathOptions={{ color: pinColors.line, weight: 2, dashArray: '5 6' }} />
        )}
        {all.map((p, i) => (
          <CircleMarker
            key={`${p.kind}-${i}`}
            center={[p.lat, p.lng]}
            radius={7}
            pathOptions={{
              color: pinColors[p.kind],
              fillColor: pinColors[p.kind],
              fillOpacity: 0.85,
              weight: 2,
            }}
          >
            <Popup>
              <span className="text-xs">
                <strong>{t(KIND_LABEL_KEYS[p.kind])}</strong>
                {p.full && (
                  <>
                    <br />
                    <span dir="auto">{p.full}</span>
                  </>
                )}
                {p.city && (
                  <>
                    <br />
                    <span dir="auto">{p.city}</span>
                  </>
                )}
                {p.approximate && (
                  <>
                    <br />
                    <em>{t('intake.map.approximate')}</em>
                  </>
                )}
              </span>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {/* Legend: three fixed roles, so it doubles as the key to what the pins mean. */}
      <div className="pointer-events-none absolute bottom-2 left-2 z-[400] flex flex-col gap-0.5 rounded-lg border border-hairline bg-panel/90 px-2 py-1.5 text-[10px] text-muted-foreground backdrop-blur">
        {present.map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: pinColors[k] }} />
            {t(KIND_LABEL_KEYS[k])}
          </span>
        ))}
      </div>
    </div>
  )
}
