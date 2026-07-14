import { useState } from 'react'
import { useFetch } from '../../hooks/useFetch'
import type { Incident } from '../../types/contract'
import { cn } from '../../lib/cn'
import { MapView } from '../artifacts/MapView'
import { Skeleton } from '../ui/Skeleton'
import { Frame } from './shell'

type Layer = 'incidents' | 'track-status'

const LAYERS: { key: Layer; label: string; hint: string }[] = [
  { key: 'incidents', label: 'Incidents', hint: 'Every recorded pollution incident.' },
  { key: 'track-status', label: 'Track Status', hint: 'Field visits with real photos, by track.' },
]

// Every recorded incident, geospatial (no photo - incidents genuinely have none), or every
// track-status field visit with its real photo(s). Recurring sites are highlighted by
// MapView's marker colors.
export function MapAllView() {
  const [layer, setLayer] = useState<Layer>('incidents')
  const incidents = useFetch<{ incidents: Incident[] }>('/incidents')
  const trackStatus = useFetch<{ trackStatus: Incident[] }>('/track-status')
  const { loading, points } =
    layer === 'incidents'
      ? { loading: incidents.loading, points: incidents.data?.incidents ?? [] }
      : { loading: trackStatus.loading, points: trackStatus.data?.trackStatus ?? [] }

  return (
    <Frame>
      <div className="relative h-full w-full">
        {loading ? (
          <Skeleton className="h-full w-full rounded-none" />
        ) : (
          // key={layer} forces a full remount on tab switch - incidents (incident_id) and
          // track-status (data_entry_id) markers can share the same raw id, and reusing one
          // map/marker instance across layers risks a stale Popup (blank, from the other
          // dataset) surviving the switch instead of being torn down.
          <MapView key={layer} incidents={points} />
        )}
        <div className="absolute left-3 top-3 z-[1000] inline-flex gap-0.5 rounded-lg border border-hairline bg-panel/90 p-0.5 text-[11px] backdrop-blur">
          {LAYERS.map(({ key, label, hint }) => (
            <button
              key={key}
              onClick={() => setLayer(key)}
              title={hint}
              className={cn(
                'rounded-md px-2.5 py-1.5 font-medium transition-colors',
                layer === key ? 'bg-accent text-white' : 'text-muted hover:text-ink',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
    </Frame>
  )
}
