import { useMemo, useState } from 'react'
import { Map as MapIcon, Share2 } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { EvidenceNode, ShipmentDetail } from '@/contracts/caseDetail'
import { evidenceCategories, evidenceTime, mappedEvidenceIds, type EvidenceCategory, type KeyEvidence } from '@/lib/evidenceCategories'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'

const SUMMARY_FIELDS = ['statement_en', 'name', 'display_name', 'event_type', 'handoff', 'observation_type', 'predicate', 'disposition', 'report_code', 'result', 'status', 'method', 'proof_type', 'verification_policy', 'recipient_type', 'purpose', 'subject', 'channel', 'position_scope', 'observed_barcode', 'measured_weight_kg', 'weight_kg', 'observed_gate', 'address_text', 'city', 'location_id', 'facility_id', 'vehicle_id', 'class_name', 'promise_kind', 'retry_limit', 'scope']
const LTR_FIELDS = new Set(['handoff', 'location_id', 'facility_id', 'vehicle_id', 'observed_barcode'])

function useFormat() {
  const { isArabic } = useLanguage()
  return (value?: string) => value ? new Date(value).toLocaleString(isArabic ? 'ar-SA-u-ca-gregory' : 'en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'UTC' }) : '—'
}

function Facts({ node, limit = 3 }: { node: EvidenceNode; limit?: number }) {
  const { propertyLabel, isArabic } = useLanguage()
  // Custody reads as a single from → to handoff instead of two disconnected ids.
  const p = node.properties
  if (p.from_id && p.to_id) node = { ...node, properties: { ...p, handoff: `${p.from_id} → ${p.to_id}` } }
  const fields = SUMMARY_FIELDS.filter(k => node.properties[k] != null && node.properties[k] !== '' && !(isArabic && k === 'statement_en' && node.properties.statement_ar)).slice(0, limit)
  const shown = isArabic && node.properties.statement_ar ? [['statement_ar', node.properties.statement_ar] as const, ...fields.map(k => [k, node.properties[k]] as const)].slice(0, limit) : fields.map(k => [k, node.properties[k]] as const)
  return <dl className="grid gap-x-3 gap-y-0.5 text-[11px] sm:grid-cols-[auto_1fr]">{shown.map(([k, v]) => <div key={k} className="contents"><dt className="text-muted-foreground">{propertyLabel(k)}</dt><dd className="min-w-0 break-words" dir={LTR_FIELDS.has(k) ? 'ltr' : 'auto'}>{String(v)}</dd></div>)}</dl>
}

function KeyCard({ item, mapped, onShow }: { item: KeyEvidence; mapped: boolean; onShow: (ids: string[], mode: 'map' | 'graph') => void }) {
  const { t, entityLabel, rootCauseLabel } = useLanguage()
  const format = useFormat()
  const n = item.node
  const provenance = [n.properties.source_quality, n.properties.verification_status].filter(Boolean).map(String)
  return <li className="flex min-w-0 flex-col gap-1.5 rounded-xl border border-border bg-card p-3">
    <div className="flex flex-wrap items-center gap-2">
      <span className="rounded-md bg-muted px-1.5 py-0.5 text-[11px] font-medium">{entityLabel(n.kind)}</span>
      {item.reasons.map((r, i) => <span key={i} className={`rounded-md px-1.5 py-0.5 text-[10px] ${r.kind === 'linked' ? 'border border-border text-muted-foreground' : 'bg-primary/10 text-primary'}`}>
        {r.kind === 'diagnosis' ? t('ops.evidence.citedDiagnosis', { cause: rootCauseLabel(r.code ?? '') }) : r.kind === 'linked' ? t('ops.evidence.linked') : r.kind === 'milestone' ? t('ops.evidence.divergentMilestone') : t(`ops.evidence.cited.${r.kind}`)}
      </span>)}
      <time className="ms-auto text-[11px] text-muted-foreground" dir="ltr">{format(evidenceTime(n))}</time>
    </div>
    <p className="break-all font-mono text-[11px] text-muted-foreground" dir="ltr">{n.id}</p>
    <Facts node={n} />
    <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-1 text-[11px]">
      {!!item.stages.length && <span className="text-muted-foreground">{t('ops.evidence.usedIn')} {item.stages.map(s => t(`ops.pipeline.short.${s}`)).join(' · ')}</span>}
      {!!provenance.length && <span className="text-muted-foreground">{t('ops.evidence.source')} {provenance.join(' · ')}</span>}
      <span className="ms-auto flex gap-2">
        <button type="button" onClick={() => onShow([n.id], 'graph')} className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"><Share2 size={12} aria-hidden="true" />{t('ops.evidence.showGraph')}</button>
        {mapped && <button type="button" onClick={() => onShow([n.id], 'map')} className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline"><MapIcon size={12} aria-hidden="true" />{t('ops.evidence.showMap')}</button>}
      </span>
    </div>
  </li>
}

const ROUTE_FILTERS = { all: [] as string[], custody: ['CustodyEvent', 'DepotReconciliation'], scans: ['ScanEvent', 'WeightObservation'], plan: ['ExpectedMilestone', 'DeliverySession', 'VehicleAssignment'], vehicle: ['GPSObservation', 'TrafficObservation', 'VehicleAssignment'], delivery: ['DeliveryAttempt', 'ContactAttempt', 'DeliveryProof', 'AuthenticationEvidence', 'SignatureEvidence', 'PhotoEvidence', 'HandoffEvidence', 'LocationPin', 'RecipientReport', 'StatusEvent'] }

function RouteTimeline({ nodes, keyIds, onPick }: { nodes: EvidenceNode[]; keyIds: Set<string>; onPick?: (id: string) => void }) {
  const { t, entityLabel } = useLanguage()
  const format = useFormat()
  const [filter, setFilter] = useState<keyof typeof ROUTE_FILTERS>('all')
  const [picked, setPicked] = useState<string | null>(null)
  const shown = nodes.filter(n => filter === 'all' || ROUTE_FILTERS[filter].includes(n.kind))
  return <div className="space-y-2">
    <div role="group" aria-label={t('ops.evidence.filter')} className="flex flex-wrap gap-1.5">{(Object.keys(ROUTE_FILTERS) as (keyof typeof ROUTE_FILTERS)[]).map(key => {
      const count = key === 'all' ? nodes.length : nodes.filter(n => ROUTE_FILTERS[key].includes(n.kind)).length
      return <button key={key} type="button" aria-pressed={filter === key} disabled={!count} onClick={() => setFilter(key)} className={`rounded-full border px-2.5 py-0.5 text-[11px] disabled:opacity-40 ${filter === key ? 'border-primary bg-primary/10 text-primary' : 'border-border'}`}>{t(`ops.evidence.routeFilter.${key}`)} <span className="text-muted-foreground">{count}</span></button>
    })}</div>
    <ol className="divide-y divide-border rounded-xl border border-border bg-card">{shown.map(n => <li key={n.id}>
      <button type="button" onClick={() => { setPicked(n.id); onPick?.(n.id) }} className={`grid w-full gap-x-3 gap-y-0.5 px-3 py-2 text-start text-xs transition-colors hover:bg-muted/40 sm:grid-cols-[8.5rem_10rem_1fr] ${keyIds.has(n.id) || picked === n.id ? 'bg-primary/5 ring-1 ring-inset ring-primary/30' : ''}`}>
      <time className="text-muted-foreground" dir="ltr">{format(evidenceTime(n))}</time>
      <span className="font-medium">{entityLabel(n.kind)}{keyIds.has(n.id) && <span className="ms-1.5 rounded bg-primary/10 px-1 text-[10px] text-primary">{t('ops.evidence.keyBadge')}</span>}</span>
      <div className="min-w-0"><Facts node={n} limit={2} /></div>
      </button>
    </li>)}</ol>
  </div>
}

function EntityGrid({ nodes }: { nodes: EvidenceNode[] }) {
  const { entityLabel } = useLanguage()
  return <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{nodes.map(n => <li key={n.id} className="min-w-0 rounded-xl border border-border bg-card p-3">
    <p className="text-[11px] font-medium text-muted-foreground">{entityLabel(n.kind)}</p>
    <p className="break-all font-mono text-[11px]" dir="ltr">{n.id}</p>
    <div className="mt-1"><Facts node={n} limit={3} /></div>
  </li>)}</ul>
}

function Inventory({ detail }: { detail: ShipmentDetail }) {
  const { t, entityLabel, propertyLabel } = useLanguage()
  const groups = Object.entries(detail.evidence.nodes.reduce<Record<string, EvidenceNode[]>>((acc, n) => { (acc[n.kind] ??= []).push(n); return acc }, {})).sort(([a], [b]) => entityLabel(a).localeCompare(entityLabel(b)))
  return <div className="space-y-2">
    <p className="text-xs text-muted-foreground">{t('ops.workspace.evidenceCount', { nodes: detail.evidence.nodes.length, edges: detail.evidence.edges.length })}</p>
    {groups.map(([kind, nodes]) => <details key={kind} className="rounded-xl border border-border bg-card px-3 py-2"><summary className="cursor-pointer text-sm font-medium">{entityLabel(kind)} <span className="text-xs text-muted-foreground">({nodes.length})</span></summary><div className="mt-2 space-y-2">{nodes.map(n => <div key={n.id} className="rounded-lg bg-muted/40 p-2"><p className="break-all font-mono text-xs" dir="ltr">{n.id}</p><dl className="mt-1 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">{Object.entries(n.properties).filter(([k, v]) => v != null && !['schema_version', 'dataset_id', 'synthetic', 'provenance', 'entity_id', 'shipment_id'].includes(k)).map(([k, v]) => <div key={k} className="min-w-0"><dt className="text-muted-foreground">{propertyLabel(k)}</dt><dd className="break-words" dir="auto">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd></div>)}</dl></div>)}</div></details>)}
  </div>
}

export function CaseEvidence({ detail, onShow, onHistory }: { detail: ShipmentDetail; onShow: (ids: string[], mode: 'map' | 'graph') => void; onHistory: () => void }) {
  const { t } = useLanguage()
  const cats = useMemo(() => evidenceCategories(detail), [detail])
  const mapped = useMemo(() => mappedEvidenceIds(detail), [detail])
  const [tab, setTab] = useState<EvidenceCategory>('key')
  const keyIds = useMemo(() => new Set(cats.key.map(k => k.node.id)), [cats])
  const counts: Record<EvidenceCategory, number> = { key: cats.key.length, route: cats.route.length, parties: cats.parties.length, context: cats.context.length, inventory: detail.evidence.nodes.length }
  return (
    <Tabs value={tab} onValueChange={(v) => setTab(v as EvidenceCategory)} className="min-h-0">
      <TabsList aria-label={t('ops.evidence.categories')}>
        {(Object.keys(counts) as EvidenceCategory[]).map(key => (
          <TabsTrigger key={key} value={key}>
            {t(`ops.evidence.tabs.${key}`)} <span className="text-muted-foreground">{counts[key]}</span>
          </TabsTrigger>
        ))}
      </TabsList>
      <ScrollArea className="max-h-[min(70svh,42rem)] pe-2">
        <TabsContent value="key" className="motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-150">
          <div className="space-y-2 pt-2">
            <p className="text-xs text-muted-foreground">{t('ops.evidence.keyIntro')}</p>
            {cats.key.length ? <ul className="grid gap-2 lg:grid-cols-2">{cats.key.map(item => <KeyCard key={item.node.id} item={item} mapped={mapped.has(item.node.id)} onShow={onShow} />)}</ul> : <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">{t('ops.evidence.noKey')}</p>}
            {cats.key.length > 1 && <button type="button" onClick={() => onShow(cats.key.map(k => k.node.id), 'graph')} className="text-xs text-primary underline underline-offset-2">{t('ops.evidence.showAllGraph')}</button>}
          </div>
        </TabsContent>
        <TabsContent value="route" className="pt-2">
          <RouteTimeline nodes={cats.route} keyIds={keyIds} onPick={(id) => onShow([id], 'graph')} />
        </TabsContent>
        <TabsContent value="parties" className="pt-2">
          <EntityGrid nodes={cats.parties} />
        </TabsContent>
        <TabsContent value="context" className="space-y-3 pt-2">
          <EntityGrid nodes={cats.context} />
          {!!cats.precedents && <p className="text-xs text-muted-foreground">{t('ops.pipeline.precedents', { count: cats.precedents })} · <button type="button" onClick={onHistory} className="text-primary underline underline-offset-2">{t('ops.evidence.openPrecedents')}</button></p>}
        </TabsContent>
        <TabsContent value="inventory" className="pt-2">
          <Inventory detail={detail} />
        </TabsContent>
      </ScrollArea>
    </Tabs>
  )
}
