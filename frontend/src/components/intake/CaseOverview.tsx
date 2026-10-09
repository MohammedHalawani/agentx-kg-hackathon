import { useMemo, type ReactNode } from 'react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '@/components/artifacts/Graph'
import { ShipmentRouteMap } from '@/components/operations/ShipmentRouteMap'
import { InvestigationPipeline } from '@/components/operations/InvestigationPipeline'
import { evidenceGraph, type PipelineStage, type ShipmentDetail } from '@/contracts/caseDetail'
import { stageEvidence } from '@/lib/pipelineEvidence'

export function CaseOverview({ detail, stage, onStage, onDeepDive, actions }: { detail:ShipmentDetail; stage:PipelineStage; onStage:(stage:PipelineStage)=>void; onDeepDive:(section:'evidence'|'diagnosis'|'map',mode?:'map'|'graph')=>void; actions:ReactNode }) {
  const { t,isArabic,rootCauseLabel } = useLanguage()
  const diagnoses=detail.reasoning?.diagnoses ?? []
  const resolved=detail.workflow_state==='RESOLVED'&&detail.outcome?.verification_status==='VERIFIED'&&!detail.outcome.invalidated
  const primary=diagnoses.find(d=>d.code==='DELIVERY_DISPUTE') ?? diagnoses.find(d=>d.code==='UNRECONCILED_CUSTODY') ?? diagnoses.find(d=>d.code==='ADDRESS_CONFLICT') ?? diagnoses.find(d=>d.code==='TRAFFIC_DELAY') ?? diagnoses[0]
  const comparisons=(detail.reasoning?.assessment?.expected_vs_actual ?? []).filter(m=>m.milestone_id)
  const divergences=comparisons.filter(m=>m.missing_due||m.late)
  const {evidence,ledger_graph}=detail
  const graph=useMemo(()=>evidenceGraph({evidence,ledger_graph}),[evidence,ledger_graph])
  const ids=stageEvidence(detail,stage)
  const shipment=detail.evidence.nodes.find(n=>n.kind==='Shipment')
  const notReceived=detail.evidence.nodes.some(n=>n.kind==='RecipientReport'&&n.properties.report_code==='NOT_RECEIVED')
  const counts=(kind:string)=>detail.evidence.nodes.filter(n=>n.kind===kind).length
  const format=(value?:string)=>value ? new Date(value).toLocaleString(isArabic?'ar-SA-u-ca-gregory':'en-GB',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—'
  return <div className="space-y-2">
    <div className="grid items-start gap-3 xl:grid-cols-[1fr_1fr_1.5fr]">
      <section className="space-y-1 rounded-xl border border-border bg-card p-3"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('ops.overview.happened')}</h3><p className="font-semibold">{resolved?t('ops.states.RESOLVED'):primary?rootCauseLabel(primary.code??''):t('ops.workspace.noDiagnosis')}</p><p className="text-sm text-muted-foreground" dir="auto">{resolved?t('ops.overview.resolvedSummary'):isArabic?primary?.summary_ar??primary?.summary:primary?.summary_en??primary?.summary}</p>{(shipment?.properties.status==='DELIVERED'||notReceived)&&<p className="text-xs">{shipment?.properties.status==='DELIVERED'&&t('ops.overview.trackingDelivered')} {notReceived&&t('ops.overview.reportNotReceived')}</p>}{primary&&!resolved&&<p className="text-[11px] text-muted-foreground">{t(primary.certainty==='travel_window_estimate'?'ops.overview.estimateCertainty':'ops.overview.supportedCertainty')}</p>}<p className="text-xs font-medium">{t(detail.workflow_state==='HUMAN_REVIEW'?'ops.overview.humanRequired':'ops.overview.evidenceSupported')}</p><button type="button" onClick={()=>onDeepDive('diagnosis')} className="text-xs text-primary underline">{t('ops.overview.assessment')}</button></section>
      <section className="space-y-1 rounded-xl border border-border bg-card p-3"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('ops.overview.journey')}</h3><p className="text-sm">{t('ops.overview.milestones',{count:comparisons.length,divergences:divergences.length})}</p>{(divergences.length?divergences:comparisons).slice(0,2).map((m,i)=><div key={m.milestone_id??i} className="border-s-2 border-chart-warning ps-2 text-xs"><p>{t('ops.workspace.expectedBy')} <time dir="ltr">{format(m.latest_at)}</time></p><p className="mt-1 text-muted-foreground">{t(m.missing_due?'ops.workspace.missing':m.late?'ops.workspace.late':'ops.workspace.observed')} <time dir="ltr">{format(m.actual_at)}</time></p></div>)}<p className="text-[10px] text-muted-foreground">{t('ops.workspace.asOf')} <time dir="ltr">{format(detail.as_of)}</time></p></section>
      <section className="space-y-1 rounded-xl border border-border bg-card p-3" aria-label={t('ops.overview.action')}><h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('ops.overview.action')}</h3><p className="text-sm font-medium" dir="auto">{(isArabic?detail.recommendation?.action_ar??detail.recommendation?.action:detail.recommendation?.action_en??detail.recommendation?.action)??t('ops.overview.noAction')}</p>{detail.recommendation&&<p className="text-xs text-muted-foreground">{t(detail.decisions?.some(d=>d.decision==='approve')?'ops.overview.basisRecorded':'ops.overview.basis',{count:detail.recommendation.evidence_ids?.length??0})}</p>}{detail.review && <div className="border-s-2 border-chart-good ps-2"><p className="text-xs font-medium">{t(`ops.review.${detail.review.verdict}`)}</p><p className="mt-1 text-[11px] leading-4 text-muted-foreground" dir="auto">{detail.review.verdict==='accept'?t('ops.overview.reviewGuard'):isArabic?detail.review.summary_ar??t('ops.workspace.gpsGuard'):detail.review.summary_en??detail.review.feedback}</p></div>}{actions}</section>
    </div>
    <InvestigationPipeline detail={detail} selected={stage} onSelect={onStage} onEvidence={()=>onDeepDive('evidence')} />
    <div className="grid gap-3 lg:grid-cols-2">
      <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-card"><header className="flex items-center justify-between gap-2 px-3 py-2"><h3 className="text-sm font-semibold">{t('ops.overview.route')}</h3><button type="button" onClick={()=>onDeepDive('map','map')} className="text-xs text-primary underline">{t('ops.overview.fullRoute')}</button></header><div className="h-52" data-stage-map={stage}><ShipmentRouteMap detail={detail} stage={stage} highlightedIds={ids} compact /></div></section>
      <section className="min-w-0 overflow-hidden rounded-xl border border-border bg-card"><header className="flex items-center justify-between gap-2 px-3 py-2"><h3 className="text-sm font-semibold">{t('ops.overview.graph')}</h3><button type="button" onClick={()=>onDeepDive('map','graph')} className="text-xs text-primary underline">{t('ops.overview.fullGraph')}</button></header><p className="px-3 text-[10px] text-muted-foreground">{t('ops.pipeline.retrieved',{nodes:graph.nodes.length,edges:graph.relationships.length})} · {t('ops.overview.custodyGps',{custody:counts('CustodyEvent'),gps:counts('GPSObservation')})}</p><div className="h-48" data-stage-graph={stage}><Graph graph={graph} highlightedIds={ids} compact /></div></section>
    </div>
  </div>
}
