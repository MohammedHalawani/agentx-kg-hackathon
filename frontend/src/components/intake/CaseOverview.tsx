import { useMemo, type ReactNode } from 'react'
import { useFocusMode, type FocusMode } from '@/hooks/useFocusMode'
import { Columns2, Map as MapIcon, Share2, Radar } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '@/components/artifacts/Graph'
import { ShipmentRouteMap } from '@/components/operations/ShipmentRouteMap'
import { InvestigationPipeline } from '@/components/operations/InvestigationPipeline'
import { evidenceGraph, type InspectStage, type ShipmentDetail } from '@/contracts/caseDetail'
import { stageFocus } from '@/lib/pipelineSteps'

const COLUMNS: Record<FocusMode, string> = { balanced: 'lg:grid-cols-[1fr_1fr]', map: 'lg:grid-cols-[7fr_3fr]', graph: 'lg:grid-cols-[3fr_7fr]' }

export function CaseOverview({ detail, stage, highlightedIds, onStage, onDeepDive, actions }: { detail: ShipmentDetail; stage: InspectStage; highlightedIds: string[]; onStage: (stage: InspectStage) => void; onDeepDive: (section: 'evidence' | 'diagnosis' | 'map', mode?: 'map' | 'graph') => void; actions: ReactNode }) {
  const { t, isArabic, rootCauseLabel } = useLanguage()
  const [chosen, setChosen] = useFocusMode()
  const diagnoses = detail.reasoning?.diagnoses ?? []
  // Auto follows the inspected/active stage; a manual choice is never overridden.
  const focus: FocusMode = chosen === 'auto' ? stageFocus(stage, diagnoses.map(d => d.code ?? '')) : chosen
  const suggested = chosen === 'auto' && focus !== 'balanced' ? focus : null
  const resolved = detail.workflow_state === 'RESOLVED' && detail.outcome?.verification_status === 'VERIFIED' && !detail.outcome.invalidated
  const primary = diagnoses.find(d => d.code === 'DELIVERY_DISPUTE') ?? diagnoses.find(d => d.code === 'UNRECONCILED_CUSTODY') ?? diagnoses.find(d => d.code === 'ADDRESS_CONFLICT') ?? diagnoses.find(d => d.code === 'TRAFFIC_DELAY') ?? diagnoses[0]
  const comparisons = (detail.reasoning?.assessment?.expected_vs_actual ?? []).filter(m => m.milestone_id)
  const divergences = comparisons.filter(m => m.missing_due || m.late)
  const { evidence, ledger_graph } = detail
  const graph = useMemo(() => evidenceGraph({ evidence, ledger_graph }), [evidence, ledger_graph])
  const shipment = detail.evidence.nodes.find(n => n.kind === 'Shipment')
  const notReceived = detail.evidence.nodes.some(n => n.kind === 'RecipientReport' && n.properties.report_code === 'NOT_RECEIVED')
  const counts = (kind: string) => detail.evidence.nodes.filter(n => n.kind === kind).length
  const format = (value?: string) => value ? new Date(value).toLocaleString(isArabic ? 'ar-SA-u-ca-gregory' : 'en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
  const card = 'space-y-1 rounded-xl border border-border bg-card p-3'
  const heading = 'text-[11px] font-semibold uppercase tracking-wide text-muted-foreground'
  const pane = (kind: 'map' | 'graph') => `min-w-0 overflow-hidden rounded-xl border bg-card transition-shadow duration-200 motion-reduce:transition-none ${suggested === kind ? 'border-primary/50 shadow-[0_0_0_3px] shadow-primary/10' : 'border-border'}`
  return <div className="grid gap-2.5 xl:grid-cols-[minmax(19rem,25rem)_minmax(0,1fr)] xl:items-start">
    <div className="grid items-stretch gap-2.5 md:grid-cols-2 xl:grid-cols-1">
      <section className={card}><h3 className={heading}>{t('ops.overview.happened')}</h3><p className="font-semibold">{resolved ? t('ops.states.RESOLVED') : primary ? rootCauseLabel(primary.code ?? '') : t('ops.workspace.noDiagnosis')}</p><p className="text-sm text-muted-foreground" dir="auto">{resolved ? t('ops.overview.resolvedSummary') : isArabic ? primary?.summary_ar ?? primary?.summary : primary?.summary_en ?? primary?.summary}</p>{(shipment?.properties.status === 'DELIVERED' || notReceived) && <p className="text-xs">{shipment?.properties.status === 'DELIVERED' && t('ops.overview.trackingDelivered')} {notReceived && t('ops.overview.reportNotReceived')}</p>}{primary && !resolved && <p className="text-[11px] text-muted-foreground">{t(primary.certainty === 'travel_window_estimate' ? 'ops.overview.estimateCertainty' : 'ops.overview.supportedCertainty')}</p>}<p className="text-xs font-medium">{t(detail.workflow_state !== 'HUMAN_REVIEW' ? 'ops.overview.evidenceSupported' : detail.review?.verdict === 'review_unavailable' ? 'ops.overview.humanRequiredReview' : detail.review?.verdict === 'human_review' ? 'ops.overview.humanRequiredJudgment' : 'ops.overview.humanRequired')}</p><button type="button" onClick={() => onDeepDive('diagnosis')} className="text-xs text-primary underline underline-offset-2">{t('ops.overview.assessment')}</button></section>
      <section className={card}><h3 className={heading}>{t('ops.overview.journey')}</h3><p className="text-sm">{t('ops.overview.milestones', { count: comparisons.length, divergences: divergences.length })}</p>{(divergences.length ? divergences : comparisons).slice(0, 2).map((m, i) => <div key={m.milestone_id ?? i} className={`border-s-2 ps-2 text-xs ${divergences.length ? 'border-chart-warning' : 'border-chart-good'}`}><p>{t('ops.workspace.expectedBy')} <time dir="ltr">{format(m.latest_at)}</time></p><p className="mt-0.5 text-muted-foreground">{t(m.missing_due ? 'ops.workspace.missing' : m.late ? 'ops.workspace.late' : 'ops.workspace.observed')} <time dir="ltr">{format(m.actual_at)}</time></p></div>)}<p className="text-[10px] text-muted-foreground">{t('ops.workspace.asOf')} <time dir="ltr">{format(detail.as_of)}</time></p></section>
      <section className={`${card} border-primary/30 md:col-span-2 xl:col-span-1`} aria-label={t('ops.overview.action')}><h3 className={heading}>{t('ops.overview.action')}</h3><p className="text-sm font-medium" dir="auto">{(isArabic ? detail.recommendation?.action_ar ?? detail.recommendation?.action : detail.recommendation?.action_en ?? detail.recommendation?.action) ?? t('ops.overview.noAction')}</p>{detail.recommendation && <p className="text-xs text-muted-foreground">{t(detail.decisions?.some(d => d.decision === 'approve') ? 'ops.overview.basisRecorded' : 'ops.overview.basis', { count: detail.recommendation.evidence_ids?.length ?? 0 })}</p>}{detail.review && <div data-testid="review-verdict" data-verdict={detail.review.verdict} className={`border-s-2 ps-2 ${detail.review.verdict === 'accept' ? 'border-chart-good' : 'border-chart-warning'}`}><p className="text-xs font-medium">{t(`ops.review.${detail.review.verdict}`)}</p><p className="mt-0.5 text-[11px] leading-4 text-muted-foreground" dir="auto">{isArabic ? detail.review.summary_ar ?? detail.review.summary_en ?? detail.review.feedback : detail.review.summary_en ?? detail.review.feedback}</p></div>}{actions}</section>
    </div>
    <div className="min-w-0 space-y-2.5">
    <InvestigationPipeline detail={detail} selected={stage} onSelect={onStage} onEvidence={() => onDeepDive('evidence')} />
    <div className="flex flex-wrap items-center gap-2">
      <div role="radiogroup" aria-label={t('ops.focus.label')} className="flex rounded-lg border border-border bg-card p-0.5">
        {([['auto', Radar], ['balanced', Columns2], ['map', MapIcon], ['graph', Share2]] as const).map(([mode, Icon]) => <button key={mode} type="button" role="radio" aria-checked={chosen === mode} onClick={() => setChosen(mode)} className={`inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px] focus-visible:outline-2 focus-visible:outline-ring ${chosen === mode ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground'}`}><Icon size={12} aria-hidden="true" />{t(`ops.focus.${mode}`)}</button>)}
      </div>
      {chosen === 'auto' && <span className="text-[11px] text-muted-foreground">{suggested ? t('ops.focus.suggested', { pane: t(`ops.focus.${suggested}Pane`) }) : t('ops.focus.autoHint')}</span>}
    </div>
      <div className={`grid gap-2.5 transition-[grid-template-columns] duration-300 ease-out motion-reduce:transition-none ${COLUMNS[focus]}`} data-focus={focus} data-viewport-key={focus}>
      <section className={pane('map')} aria-label={t('ops.overview.route')}><header className="flex items-center justify-between gap-2 px-3 py-1.5"><h3 className="text-sm font-semibold">{t('ops.overview.route')}</h3><button type="button" onClick={() => onDeepDive('map', 'map')} className="text-xs text-primary underline underline-offset-2">{t('ops.overview.fullRoute')}</button></header><div className="h-[clamp(16rem,42vh,26rem)] xl:h-[max(18rem,calc(100svh-27rem))]" data-stage-map={stage}><ShipmentRouteMap detail={detail} stage={stage} highlightedIds={highlightedIds} compact /></div></section>
      <section className={pane('graph')} aria-label={t('ops.overview.graph')}><header className="flex items-center justify-between gap-2 px-3 py-1.5"><h3 className="text-sm font-semibold">{t('ops.overview.graph')}</h3><button type="button" onClick={() => onDeepDive('map', 'graph')} className="text-xs text-primary underline underline-offset-2">{t('ops.overview.fullGraph')}</button></header><p className="px-3 text-[10px] text-muted-foreground">{t('ops.pipeline.retrieved', { nodes: graph.nodes.length, edges: graph.relationships.length })} · {t('ops.overview.custodyGps', { custody: counts('CustodyEvent'), gps: counts('GPSObservation') })} · {t('ops.focus.highlighted', { count: highlightedIds.length })}</p><div className="h-[calc(clamp(16rem,42vh,26rem)-1rem)] xl:h-[max(17rem,calc(100svh-28rem))]" data-stage-graph={stage}><Graph graph={graph} highlightedIds={highlightedIds} compact viewportKey={focus} /></div></section>
    </div>
    </div>
  </div>
}
