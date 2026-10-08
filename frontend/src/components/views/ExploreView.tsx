import { useRef, useState } from 'react'
import { BrainCircuit, Map, Maximize2, RefreshCw, RotateCcw, Workflow } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useFetch } from '../../hooks/useFetch'
import type { GraphNode, SubGraph } from '../../types/contract'
import { SHIPMENT_FILTERS, type ExploreData, type ExploreShipment, type ShipmentFilter } from '../../types/explore'
import { cn } from '../../lib/cn'
import { Graph } from '../artifacts/Graph'
import { SchemaView } from './SchemaView'
import { ExploreMap } from './ExploreMap'
import { ExploreShipmentCard, ShipmentStatus } from './ExploreShipmentCard'

type Lens = 'map' | 'graph' | 'schema'

function ShipmentGraph({ shipmentId, onNodeSelect }: { shipmentId: string; onNodeSelect: (node: GraphNode) => void }) {
  const { data, loading, error, refetch } = useFetch<SubGraph>(`/graph?shipment_id=${encodeURIComponent(shipmentId)}`)
  const { t } = useLanguage()
  if (loading) return <div role="status" className="grid h-full place-items-center">{t('explore.loading')}</div>
  if (error) return <div role="alert" className="grid h-full place-items-center"><button onClick={refetch}>{t('explore.error')} · {t('explore.retry')}</button></div>
  return data?.nodes.length ? <Graph graph={data} onNodeSelect={onNodeSelect} /> : <div role="status" className="grid h-full place-items-center">{t('explore.noGraphData')}</div>
}

export function ExploreView({ onOpenCase }: { onOpenCase: (shipment: ExploreShipment) => void }) {
  const [lens, setLens] = useState<Lens>('map')
  const [filter, setFilter] = useState<ShipmentFilter>('needs_attention')
  const [limit, setLimit] = useState(25)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const rootRef = useRef<HTMLDivElement>(null)
  const { t, isArabic } = useLanguage()
  const { data, loading, error, refetch } = useFetch<ExploreData>(`/explore?filter=${filter}&limit=${limit}`)
  const selected = data?.shipments.find(s => s.shipment_id === selectedId) ?? null
  const pickNode = (node: GraphNode) => {
    if (!node.labels.includes('Shipment')) return
    const id = String(node.properties.shipment_id ?? node.caption)
    if (data?.shipments.some(s => s.shipment_id === id)) setSelectedId(id)
  }
  const lenses = [{ key: 'map' as const, Icon: Map }, { key: 'graph' as const, Icon: BrainCircuit }, { key: 'schema' as const, Icon: Workflow }]

  return (
    <div ref={rootRef} className="flex h-full flex-col bg-background" dir={isArabic ? 'rtl' : 'ltr'}>
      <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-2.5">
        <div className="inline-flex rounded-lg border border-border p-0.5" aria-label={t('explore.lens')}>
          {lenses.map(({ key, Icon }) => <button key={key} onClick={() => setLens(key)} aria-pressed={lens === key} className={cn('inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-ring', lens === key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground')}><Icon size={15} aria-hidden="true" />{t(`explore.${key}`)}</button>)}
        </div>
        <button onClick={() => { setSelectedId(null); refetch() }} disabled={loading} aria-label={t('explore.refresh')} className="rounded-lg border border-border p-2 disabled:opacity-50"><RefreshCw size={15} aria-hidden="true" /></button>
        <button onClick={() => setSelectedId(null)} disabled={!selected} className="inline-flex items-center gap-1.5 rounded-lg border border-border px-2 py-1.5 text-xs disabled:opacity-50"><RotateCcw size={14} aria-hidden="true" />{t('explore.reset')}</button>
        {typeof document !== 'undefined' && document.fullscreenEnabled && <button aria-label={t('explore.fullscreen')} onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void rootRef.current?.requestFullscreen() }} className="rounded-lg border border-border p-2"><Maximize2 size={15} aria-hidden="true" /></button>}
      </div>
      {lens !== 'schema' && <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border px-4 py-2">
        <div className="flex flex-wrap gap-1" aria-label={t('explore.filtersLabel')}>
          {SHIPMENT_FILTERS.map(key => <button key={key} aria-pressed={filter === key} onClick={() => { setFilter(key); setSelectedId(null) }} className={cn('rounded-lg border px-2.5 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-ring', filter === key ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card text-muted-foreground')}>
            {t(`explore.filters.${key}`)}{data && <> <span className="ms-1 tabular-nums" dir="ltr">({data.counts[key]})</span></>}
          </button>)}
        </div>
        <label className="ms-auto flex items-center gap-1.5 text-xs text-muted-foreground">{t('explore.limit')}<select aria-label={t('explore.limit')} value={limit} onChange={e => { setLimit(Number(e.target.value)); setSelectedId(null) }} className="rounded-md border border-border bg-card px-1 py-1 text-foreground">{[10, 25, 50].map(n => <option key={n} value={n}>{n}</option>)}</select></label>
      </div>}
      <div className="min-h-0 flex-1 overflow-auto">
        {lens === 'schema' ? <SchemaView /> : loading ? <div role="status" className="grid h-full place-items-center text-sm text-muted-foreground">{t('explore.loading')}</div> : error ? <div role="alert" className="grid h-full place-items-center p-6"><div className="text-center"><p>{t('explore.error')}</p><button onClick={refetch} className="mt-3 rounded-lg border border-border px-3 py-2">{t('explore.retry')}</button></div></div> : !data?.shipments.length ? <div role="status" className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{t('explore.empty')}</div> : <div className="flex min-h-full flex-col lg:h-full lg:flex-row">
          <div className="relative min-h-80 flex-1 lg:min-h-0" dir="ltr">
            {lens === 'map' ? <ExploreMap key={`${filter}-${limit}`} shipments={data.shipments} selected={selected} onSelect={s => setSelectedId(s.shipment_id)} /> : selected ? <ShipmentGraph shipmentId={selected.shipment_id} onNodeSelect={pickNode} /> : <Graph graph={data.graph} onNodeSelect={pickNode} />}
          </div>
          <aside className="shrink-0 space-y-3 border-t border-border bg-background p-3 lg:w-80 lg:overflow-y-auto lg:border-s lg:border-t-0" aria-label={t('explore.shipmentList')}>
            <p role="status" className="text-xs text-muted-foreground">{t('explore.showing', { returned: data.returned, total: data.total })}{data.truncated && ` · ${t('explore.bounded')}`}</p>
            <p className="text-xs text-muted-foreground">{t('explore.synthetic')}</p>
            {selected && <ExploreShipmentCard shipment={selected} onOpenCase={onOpenCase} />}
            <ul className="space-y-1">
              {data.shipments.map(s => <li key={s.shipment_id}><button onClick={() => setSelectedId(s.shipment_id)} aria-pressed={selectedId === s.shipment_id} className={cn('w-full space-y-1 rounded-lg border p-2 text-start focus-visible:outline-2 focus-visible:outline-ring', selectedId === s.shipment_id ? 'border-primary bg-accent' : 'border-border bg-card hover:bg-accent')}><span dir="ltr" className="block font-mono text-xs font-semibold">{s.shipment_id}</span><ShipmentStatus shipment={s} />{s.city && <span dir="auto" className="block text-xs text-muted-foreground">{s.city}</span>}</button></li>)}
            </ul>
          </aside>
        </div>}
      </div>
    </div>
  )
}
