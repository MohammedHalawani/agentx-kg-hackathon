import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, Polyline, Popup, TileLayer } from 'react-leaflet'
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet'
import { cssVar } from '../../lib/theme'
import type { RoutePoint } from '../../types/agent'

// Colour by role, fixed per kind - never by the order the backend happened to return them
// (see the dataviz skill's non-negotiables). Warehouse is the neutral origin, the delivery
// address is where it was meant to go, and `home` only appears when it differs from the
// delivery address, which is exactly the address-conflict case.
const STYLE: Record<RoutePoint['kind'], { color: string; label: string }> = {
  warehouse: { color: '--color-chart-blue', label: 'Origin warehouse' },
  delivery: { color: '--color-chart-orange', label: 'Delivery address' },
  home: { color: '--color-chart-aqua', label: "Customer's address" },
}

const KIND_ORDER: RoutePoint['kind'][] = ['warehouse', 'delivery', 'home']

export function ShipmentMap({ origin, points }: { origin: RoutePoint | null; points: RoutePoint[] }) {
  const all = [...(origin ? [origin] : []), ...points]
  if (!all.length) {
    return (
      <div className="grid h-full place-items-center p-4 text-center text-xs text-muted">
        This shipment has no mapped coordinates.
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
          <Polyline positions={line} pathOptions={{ color: cssVar('--color-chart-blue'), weight: 2, dashArray: '5 6' }} />
        )}
        {all.map((p, i) => (
          <CircleMarker
            key={`${p.kind}-${i}`}
            center={[p.lat, p.lng]}
            radius={7}
            pathOptions={{
              color: cssVar(STYLE[p.kind].color),
              fillColor: cssVar(STYLE[p.kind].color),
              fillOpacity: 0.85,
              weight: 2,
            }}
          >
            <Popup>
              <span className="text-xs">
                <strong>{STYLE[p.kind].label}</strong>
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
                    <em>approximate — city centre</em>
                  </>
                )}
              </span>
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      {/* Legend: three fixed roles, so it doubles as the key to what the pins mean. */}
      <div className="pointer-events-none absolute bottom-2 left-2 z-[400] flex flex-col gap-0.5 rounded-lg border border-hairline bg-panel/90 px-2 py-1.5 text-[10px] text-muted backdrop-blur">
        {present.map((k) => (
          <span key={k} className="flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: cssVar(STYLE[k].color) }} />
            {STYLE[k].label}
          </span>
        ))}
      </div>
    </div>
  )
}
