import { useState } from 'react'
import 'leaflet/dist/leaflet.css'
import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import type { LatLngBoundsExpression } from 'leaflet'
import type { Incident } from '../../types/contract'
import { cssVar } from '../../lib/theme'
import { PhotoLightbox, type LightboxState } from './PhotoLightbox'

// Leaflet's Popup calls L.DomEvent.disableClickPropagation on its content, which stops a click's
// NATIVE bubbling before it reaches React's root-level delegated listener - so a normal `onClick`
// prop silently never fires on anything inside a Popup. Assigning the native `onclick` property
// via a ref runs directly on the element itself, unaffected by that ancestor-level stop.
function nativeClick(handler: () => void) {
  return (el: HTMLImageElement | null) => {
    if (el) el.onclick = handler
  }
}

export function MapView({ incidents }: { incidents: Incident[] }) {
  const [lightbox, setLightbox] = useState<LightboxState | null>(null)
  const points = incidents.filter((i) => typeof i.lat === 'number' && typeof i.lon === 'number')
  if (!points.length) {
    return (
      <div className="grid h-full place-items-center p-6 text-center text-sm text-muted">
        No mappable locations in this result (housing data has no coordinates).
      </div>
    )
  }
  const base = cssVar('--marker')
  const recurring = cssVar('--marker-recurring')
  // a single point has no meaningful bounds (Leaflet over-zooms on a degenerate box) — center on it
  const single = points.length === 1
  const coords = points.map((p) => [p.lat, p.lon] as [number, number])

  return (
    <>
      <MapContainer
        center={single ? coords[0] : undefined}
        zoom={single ? 13 : undefined}
        bounds={single ? undefined : (coords as LatLngBoundsExpression)}
        boundsOptions={{ padding: [30, 30], maxZoom: 14 }}
        scrollWheelZoom
        className="h-full w-full"
      >
        {/* muted light basemap (Carto Positron) so the accent incident markers read as the figure */}
        <TileLayer
          attribution="&copy; OpenStreetMap &copy; CARTO"
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        {points.map((i, idx) => {
          const color = i.recurring ? recurring : base
          const label = i.track || (i.categories ?? []).join(', ') || 'incident'
          return (
            <CircleMarker
              key={i.key ?? idx}
              center={[i.lat, i.lon]}
              radius={7}
              pathOptions={{ color, fillColor: color, fillOpacity: 0.7, weight: 1.5 }}
            >
              <Popup>
                <div className="text-xs">
                  {/* Incidents never show a photo here, even when the backend carries one on
                      i.image (a real per-frame lens photo) - only track-status (i.images, real
                      field visits) ever gets a photo in this UI. */}
                  {i.images && i.images.length > 0 && (
                    <div className={i.images.length > 1 ? 'mb-1.5 grid grid-cols-2 gap-1' : 'mb-1.5'}>
                      {i.images.map((src, photoIdx) => (
                        <img
                          key={photoIdx}
                          src={src}
                          alt={label}
                          loading="lazy"
                          ref={nativeClick(() => setLightbox({ images: i.images!, index: photoIdx, title: label }))}
                          className="h-20 w-full cursor-zoom-in rounded-md object-cover transition-opacity hover:opacity-85"
                        />
                      ))}
                    </div>
                  )}
                  <div className="font-medium">{label}</div>
                  {i.status && <div>status: {i.status}</div>}
                  {i.entry_action && <div>{i.entry_action}</div>}
                  {i.notes && <div className="text-muted">{i.notes}</div>}
                  {i.date && <div>{i.date}</div>}
                  {typeof i.frames === 'number' && (
                    <div>{i.frames} camera frame{i.frames === 1 ? '' : 's'} merged here</div>
                  )}
                  {i.trip_id != null && <div>survey drive {String(i.trip_id)}</div>}
                  {i.recurring && <div>recurring - seen again on a later drive</div>}
                </div>
              </Popup>
            </CircleMarker>
          )
        })}
      </MapContainer>
      <PhotoLightbox
        state={lightbox}
        onIndexChange={(index) => setLightbox((prev) => (prev ? { ...prev, index } : prev))}
        onClose={() => setLightbox(null)}
      />
    </>
  )
}
