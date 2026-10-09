import { useCursorPage } from '@/hooks/useCursorPage'
import { useMemo, useRef, useState } from 'react'
import { BrainCircuit, Map, Maximize2, RefreshCw, RotateCcw, Workflow } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useExploreData } from '@/hooks/useExploreData'
import { evidenceGraph, type ShipmentDetail } from '@/contracts/caseDetail'
import { ShipmentRouteMap } from '@/components/operations/ShipmentRouteMap'
import { CursorPagination } from '@/components/operations/Pagination'
import { ErrorState } from '@/components/operations/ErrorState'
import { ResponsiveDisclosure } from '@/components/operations/ResponsiveDisclosure'
import { FilterBar, FilterField } from '@/components/operations/FilterBar'
import { SearchInput } from '@/components/operations/SearchInput'
import { SHIPMENT_FILTERS, type ExploreShipment, type ShipmentFilter } from '../../types/explore'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '../../lib/cn'
import { Graph } from '../artifacts/Graph'
import { SchemaView } from './SchemaView'
import { ExploreMap } from './ExploreMap'
import { ExploreShipmentCard, ShipmentStatus } from './ExploreShipmentCard'
import { useFetch } from '../../hooks/useFetch'

type Lens = 'map' | 'graph' | 'schema'

function ShipmentGraph({ shipmentId }: { shipmentId: string }) {
  const { data, loading, error, refetch } = useFetch<ShipmentDetail>(`/shipments/${encodeURIComponent(shipmentId)}/context`)
  const { t } = useLanguage()
  if (loading) return <div role="status" className="grid h-full place-items-center">{t('explore.loading')}</div>
  if (error) return <ErrorState onRetry={refetch} />
  if (!data?.evidence?.nodes.length) {
    return (
      <div role="status" className="grid h-full place-items-center">
        <button type="button" onClick={refetch} className="rounded-lg border border-border px-3 py-2 text-sm">
          {t('explore.noGraphData')} · {t('explore.retry')}
        </button>
      </div>
    )
  }
  return <Graph graph={evidenceGraph(data)} />
}

function ShipmentMap({ shipment, onSelect }: { shipment: ExploreShipment; onSelect: (s: ExploreShipment) => void }) {
  const { data, loading, error, refetch } = useFetch<ShipmentDetail>(`/shipments/${encodeURIComponent(shipment.shipment_id)}/context`)
  const { t } = useLanguage()
  if (loading) return <div role="status">{t('explore.loading')}</div>
  if (error || (data && !data.evidence?.nodes)) return <ErrorState onRetry={refetch} />
  return data ? <ShipmentRouteMap detail={data} shipment={shipment} onSelect={onSelect} /> : null
}

function matchesExploreSearch(shipment: ExploreShipment, query: string) {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return shipment.shipment_id.toLowerCase().includes(q) || Boolean(shipment.case_id?.toLowerCase().includes(q))
}

export function ExploreView({ onOpenCase }: { onOpenCase?: (shipment: ExploreShipment) => void }) {
  const [lens, setLens] = useState<Lens>('map')
  const [filter, setFilter] = useState<ShipmentFilter>('needs_attention')
  const [limit, setLimit] = useState(25)
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const pager = useCursorPage()
  const cursor = pager.cursor
  const offset = pager.offset
  const [extraFilters, setExtraFilters] = useState({ city: 'all', cause: 'all', service_type: 'all', shipment_class: 'all' })
  const rootRef = useRef<HTMLDivElement>(null)
  const { t, isArabic, rootCauseLabel } = useLanguage()
  const { data, loading, error, refetch } = useExploreData(filter, limit, cursor, extraFilters)
  const listedShipments = useMemo(
    () => (data?.shipments ?? []).filter(s => matchesExploreSearch(s, search)),
    [data?.shipments, search],
  )
  const selected = data?.shipments.find((s) => s.shipment_id === selectedId) ?? null

  const lenses = [
    { key: 'map' as const, Icon: Map, disabled: false },
    { key: 'graph' as const, Icon: BrainCircuit },
    { key: 'schema' as const, Icon: Workflow },
  ]

  return (
    <div ref={rootRef} className="flex h-full flex-col overflow-hidden bg-background" dir={isArabic ? 'rtl' : 'ltr'}>
      <div className="max-h-[55dvh] shrink-0 space-y-3 overflow-y-auto border-b border-border px-4 py-4 sm:px-6 lg:max-h-none">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-display text-xl font-bold text-ink">{t('nav.explore')}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t('explore.subtitle')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Tabs value={lens} onValueChange={(value) => setLens(value as Lens)} className="gap-0">
              <TabsList
                aria-label={t('explore.lens')}
                className="h-auto gap-0.5 rounded-lg border border-border bg-card p-0.5"
              >
                {lenses.map(({ key, Icon }) => (
                  <TabsTrigger
                    key={key}
                    value={key}
                    className="inline-flex items-center gap-1.5 rounded-md border-b-0 px-3 py-1.5 text-sm data-[state=active]:bg-primary data-[state=active]:text-primary-foreground"
                  >
                    <Icon size={15} aria-hidden="true" />
                    {t(`explore.${key}`)}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
            <button type="button" onClick={() => { setSelectedId(null); refetch() }} disabled={loading} aria-label={t('explore.refresh')} className="rounded-lg border border-border bg-card p-2 disabled:opacity-50">
              <RefreshCw size={15} aria-hidden="true" />
            </button>
            <button type="button" onClick={() => setSelectedId(null)} disabled={!selected} className="inline-flex items-center gap-1.5 rounded-lg border border-border bg-card px-2 py-1.5 text-xs disabled:opacity-50">
              <RotateCcw size={14} aria-hidden="true" />
              {t('explore.reset')}
            </button>
            {typeof document !== 'undefined' && document.fullscreenEnabled && (
              <button
                type="button"
                aria-label={t('explore.fullscreen')}
                onClick={() => {
                  if (document.fullscreenElement) void document.exitFullscreen()
                  else void rootRef.current?.requestFullscreen()
                }}
                className="rounded-lg border border-border bg-card p-2"
              >
                <Maximize2 size={15} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>

        {lens !== 'schema' && (
          <ResponsiveDisclosure title={t('ops.disclosure.filters')} defaultOpen>
            <FilterBar>
              <SearchInput
                id="explore-search"
                value={search}
                onChange={v => { setSearch(v); if (v.trim()) setSelectedId(null) }}
                placeholder={t('explore.search')}
              />
              <FilterField label={t('explore.limit')} className="max-w-[8rem]">
                <select
                  aria-label={t('explore.limit')}
                  value={limit}
                  onChange={(e) => { setLimit(Number(e.target.value)); setSelectedId(null); pager.reset() }}
                  className="rounded-md border border-border bg-card px-2 py-1.5 text-foreground"
                >
                  {[25, 50, 100].map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </FilterField>
              {(['city', 'cause', 'service_type', 'shipment_class'] as const).map(key => (
                <FilterField key={key} label={t(`ops.filters.${key}`)}>
                  <select
                    value={extraFilters[key]}
                    onChange={e => { setExtraFilters(f => ({ ...f, [key]: e.target.value })); pager.reset(); setSelectedId(null) }}
                    className="rounded-md border border-border bg-card p-1.5"
                  >
                    <option value="all">{t('ops.filters.all')}</option>
                    {(data?.metadata?.filter_choices?.[key] ?? []).map(value => (
                      <option key={value} value={value}>{key === 'cause' ? rootCauseLabel(value) : key === 'city' ? t(`cities.${value}`) : value}</option>
                    ))}
                  </select>
                </FilterField>
              ))}
            </FilterBar>
            <div className="flex flex-wrap gap-1 pt-1" role="group" aria-label={t('explore.filtersLabel')}>
              {SHIPMENT_FILTERS.map((key) => (
                <button
                  key={key}
                  type="button"
                  aria-pressed={filter === key}
                  onClick={() => { setFilter(key); setSelectedId(null); pager.reset() }}
                  className={cn(
                    'rounded-lg border px-2.5 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-ring',
                    filter === key ? 'border-primary bg-primary text-primary-foreground' : 'border-border bg-card text-muted-foreground',
                  )}
                >
                  {t(`explore.filters.${key}`)}
                  {data && typeof data.counts[key] === 'number' && (
                    <span className="ms-1 tabular-nums" dir="ltr">
                      ({data.counts[key]})
                    </span>
                  )}
                </button>
              ))}
            </div>
          </ResponsiveDisclosure>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {lens === 'schema' ? (
          <SchemaView />
        ) : loading ? (
          <div role="status" className="grid h-full place-items-center text-sm text-muted-foreground">{t('explore.loading')}</div>
        ) : error ? (
          <div role="alert" className="grid h-full place-items-center p-6">
            <div className="text-center">
              <p>{t('explore.error')}</p>
              <button type="button" onClick={refetch} className="mt-3 rounded-lg border border-border px-3 py-2">{t('explore.retry')}</button>
            </div>
          </div>
        ) : !data?.shipments.length ? (
          <div role="status" className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{t('explore.empty')}</div>
        ) : !listedShipments.length ? (
          <div role="status" className="grid h-full place-items-center p-6 text-center text-sm text-muted-foreground">{t('common.noResults')}</div>
        ) : (
          <div className="flex min-h-full flex-col lg:h-full lg:flex-row">
            <div className="relative min-h-80 flex-1 lg:min-h-0" dir="ltr">
              {lens === 'map' ? (
                selected ? <ShipmentMap key={selected.shipment_id} shipment={selected} onSelect={(s) => setSelectedId(s.shipment_id)} /> : <ExploreMap key={`${filter}-${limit}-${cursor}`} shipments={data.shipments} selected={null} onSelect={(s) => setSelectedId(s.shipment_id)} />
              ) : selected ? (
                <ShipmentGraph shipmentId={selected.shipment_id} />
              ) : (
                <Graph graph={data.graph} />
              )}
            </div>
            <aside className="shrink-0 space-y-3 border-t border-border bg-background p-3 lg:w-80 lg:overflow-y-auto lg:border-s lg:border-t-0" aria-label={t('explore.shipmentList')}>
              <p role="status" className="text-xs text-muted-foreground">
                {search.trim()
                  ? t('explore.showing', { returned: listedShipments.length, total: data.total })
                  : t('explore.showing', { returned: data.returned, total: data.total })}
                {data.truncated && ` · ${t('explore.bounded')}`}
              </p>
              {selected && onOpenCase && <ExploreShipmentCard shipment={selected} onOpenCase={onOpenCase} />}
              <ul className="space-y-1">
                {listedShipments.map((s) => (
                  <li key={s.shipment_id}>
                    <button
                      type="button"
                      onClick={() => setSelectedId(s.shipment_id)}
                      aria-pressed={selectedId === s.shipment_id}
                      className={cn(
                        'w-full space-y-1 rounded-lg border p-2 text-start focus-visible:outline-2 focus-visible:outline-ring',
                        selectedId === s.shipment_id ? 'border-primary bg-accent' : 'border-border bg-card hover:bg-accent',
                      )}
                    >
                      <span dir="ltr" className="block font-mono text-xs font-semibold">{s.shipment_id}</span>
                      <ShipmentStatus shipment={s} />
                      {s.city && <span dir="auto" className="block text-xs text-muted-foreground">{t(`cities.${s.city}`)}</span>}
                    </button>
                  </li>
                ))}
              </ul>
              {!search.trim() && (
                <CursorPagination total={data.total} limit={limit} cursorStart={offset} nextCursor={data.next_cursor ?? null} prevCursor={pager.hasPrevious ? 'visited-page' : null} onNext={() => { pager.next(data.next_cursor, limit); setSelectedId(null) }} onPrev={() => { pager.previous(limit); setSelectedId(null) }} onLimitChange={n => { setLimit(n); pager.reset(); setSelectedId(null) }} />
              )}
            </aside>
          </div>
        )}
      </div>
    </div>
  )
}
