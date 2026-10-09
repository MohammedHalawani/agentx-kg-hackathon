import { useMemo, useState } from 'react'
import { useFetch } from '@/hooks/useFetch'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { operationsPost } from '@/lib/operationsClient'
import type { InspectStage, ShipmentDetail } from '@/contracts/caseDetail'
import { evidenceGraph } from '@/contracts/caseDetail'
import { Graph } from '@/components/artifacts/Graph'
import { CaseWorkflowBadge } from '@/components/operations/StatusBadge'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'
import { CaseOverview } from './CaseOverview'
import { CaseEvidence } from './CaseEvidence'
import { useCompactSidebar } from '@/hooks/useCompactSidebar'
import { activeStage } from '@/lib/pipelineSteps'
import { useCasePipeline } from '@/hooks/useCasePipeline'
import { InvestigationPipeline } from '@/components/operations/InvestigationPipeline'
import { stageEvidence } from '@/lib/pipelineEvidence'
import { ShipmentRouteMap } from '@/components/operations/ShipmentRouteMap'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { useCursorPage } from '@/hooks/useCursorPage'
import { Timeline } from '@/components/operations/Timeline'
import { CursorPagination } from '@/components/operations/Pagination'
import { adaptAudit, pageQuery, type ApiAuditEvent } from '@/adapters/operationsApi'

const SECTIONS = ['overview', 'evidence', 'diagnosis', 'recommendation', 'review', 'map', 'history'] as const
type Section = typeof SECTIONS[number]
function CaseAudit({ caseId }: { caseId: string }) {
  const { t } = useLanguage()
  const pager = useCursorPage()
  const [limit, setLimit] = useState(25)
  const { data, loading, error, refetch } = useOperationsPage<ApiAuditEvent>(`/audit?${pageQuery({ case_id: caseId, limit, cursor: pager.cursor })}`)
  if (loading) return <LoadingState label={t('ops.audit.loading')} />
  if (error) return <ErrorState onRetry={refetch} />
  return <div className="space-y-3"><h3 className="font-semibold">{t('ops.audit.title')}</h3>{data?.items.length ? <Timeline events={data.items.map(adaptAudit)} /> : <p className="text-sm text-muted-foreground">{t('ops.audit.emptyTitle')}</p>}<CursorPagination total={data?.filtered_total ?? 0} limit={limit} cursorStart={pager.offset} nextCursor={data?.next_cursor ?? null} prevCursor={pager.hasPrevious ? 'visited' : null} onNext={() => pager.next(data?.next_cursor, limit)} onPrev={() => pager.previous(limit)} onLimitChange={n => { setLimit(n); pager.reset() }} /></div>
}

export function OperationsCaseDetail({ caseId, shipmentId, onBack }: { caseId?: string; shipmentId: string; onBack: () => void }) {
  const { t, isArabic, rootCauseLabel, entityLabel } = useLanguage()
  useCompactSidebar()
  const { data: fetched, loading, error, refetch } = useFetch<ShipmentDetail>(caseId ? `/cases/${encodeURIComponent(caseId)}` : `/shipments/${encodeURIComponent(shipmentId)}/context`, true)
  const { live, unavailable } = useCasePipeline(caseId, refetch, fetched?.state_version)
  const data = useMemo(() => fetched && live && fetched.pipeline ? { ...fetched, pipeline: { ...fetched.pipeline, events: live.events.length ? live.events : fetched.pipeline.events, status: live.status } } : fetched, [fetched, live])
  const [pinnedStage, setPinnedStage] = useState<InspectStage | null>(null)
  // Evidence chosen from the Evidence tab overrides stage emphasis until a stage is inspected again.
  const [focusIds, setFocusIds] = useState<string[] | null>(null)
  const stage = pinnedStage ?? activeStage(data)
  const inspectStage = (next: InspectStage) => { setFocusIds(null); setPinnedStage(next) }
  const highlightedIds = focusIds ?? (data ? stageEvidence(data, stage) : [])
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [outcomeType, setOutcomeType] = useState('')
  const [success, setSuccess] = useState('')
  const [evidenceIds, setEvidenceIds] = useState<string[]>([])
  const [section, setSection] = useState<Section>('overview')
  const [mapMode, setMapMode] = useState<'map' | 'graph'>('map')
  // Fresh evidence assessment is a proposal, never the mutable workflow authority.
  const state = data?.workflow_state
  const command = async (action: string, body: Record<string, unknown> = {}) => {
    if (!caseId || pending) return
    setPending(true); setActionError(null)
    try { await operationsPost(`/cases/${encodeURIComponent(caseId)}/${action}`, { ...body, idempotency_key: crypto.randomUUID(), expected_version: data?.state_version }); refetch() }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Request failed') }
    finally { setPending(false) }
  }
  const operatorControls = data && (caseId && (state === 'AWAITING_APPROVAL' || state === 'HUMAN_REVIEW') && <section className="space-y-1 border-t border-border pt-2" aria-label={t('ops.automation.humanDecision')}><h4 className="text-xs font-semibold">{t('ops.automation.humanDecision')}</h4><p className="text-[11px] leading-4 text-muted-foreground">{t(state === 'HUMAN_REVIEW' ? 'ops.automation.humanReason' : 'ops.automation.authorizationReason')}</p><div className="flex flex-wrap gap-2">{(['approve', 'reject', 'request_evidence', 'escalate'] as const).map(decision => <button key={decision} type="button" disabled={pending || data.state_version == null || (decision === 'approve' && (!data.recommendation_id || !data.recommendation))} onClick={() => void command('decision', { decision })} className="rounded-lg border border-border bg-card px-2 py-1 text-xs disabled:opacity-50">{t(`ops.actions.${decision}`)}</button>)}<button type="button" disabled={pending} onClick={() => void command('reanalyze')} className="text-[11px] text-muted-foreground underline underline-offset-2">{t('ops.actions.reanalyze')}</button></div></section>)
  return <section className="mx-auto max-w-[1600px] space-y-3" dir={isArabic ? 'rtl' : 'ltr'}>
    <header className="flex flex-wrap items-center gap-3"><button type="button" onClick={onBack} className="rounded-lg border border-border px-2 py-1.5 text-xs">{t('ops.workspace.back')}</button><h2 className="font-mono text-lg" dir="ltr">{shipmentId}</h2>{state && <CaseWorkflowBadge state={state} />}{data?.priority&&<span className="text-xs text-muted-foreground">{t(`ops.priority.${data.priority}`)}</span>}{data?.synthetic && <span className="text-xs text-muted-foreground">{t('ops.simulation.label')}</span>}{caseId && state && ['RESOLVED', 'REJECTED', 'ESCALATED'].includes(state) && data?.state_version != null && <button type="button" disabled={pending} onClick={() => void command('decision', { decision: 'reopen' })} className="ms-auto rounded-lg border border-border px-2 py-1.5 text-xs disabled:opacity-50">{t('ops.actions.reopen')}</button>}<button type="button" disabled={pending || loading} onClick={refetch} className={`${caseId && state && ['RESOLVED', 'REJECTED', 'ESCALATED'].includes(state) ? '' : 'ms-auto '}rounded-lg border border-border px-2 py-1.5 text-xs disabled:opacity-50`}>{t('explore.refresh')}</button></header>
    {loading && !data ? <LoadingState label={t('explore.loading')} /> : error || (data && !data.evidence?.nodes) ? <ErrorState onRetry={refetch} /> : data && <>
      {caseId && (state === 'OPEN' || state === 'REOPENED' || state === 'INVESTIGATING') && <p role="status" className="text-[11px] leading-4 text-muted-foreground">{t(state === 'INVESTIGATING' ? 'ops.automation.processing' : 'ops.automation.queued')}</p>}
      {!caseId && <p className="text-sm text-muted-foreground">{t('ops.workspace.evidenceOnly')}</p>}
      {actionError && <ErrorState message={t('ops.error.action')} onRetry={() => { setActionError(null); refetch() }} />}
      <div className="flex flex-wrap gap-2 border-b border-border pb-3" role="group" aria-label={t('ops.workspace.sections')}>
        {SECTIONS.map(key => <button key={key} type="button" aria-pressed={section === key} onClick={() => setSection(key)} className={`rounded-lg px-2.5 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-ring ${section === key ? 'bg-primary text-primary-foreground' : 'border border-border bg-card text-muted-foreground'}`}>{t(`ops.workspace.${key}`)}</button>)}
      </div>
      {unavailable && <p role="status" className="text-xs text-muted-foreground">{t('ops.pipeline.disconnected')}</p>}
      {section === 'overview' && <CaseOverview detail={data} stage={stage} highlightedIds={highlightedIds} onStage={inspectStage} actions={operatorControls} onDeepDive={(target, mode) => { setSection(target); if(mode) setMapMode(mode) }} />}
      {section === 'evidence' && <CaseEvidence detail={data} onHistory={() => setSection('history')} onShow={(ids, mode) => { setFocusIds(ids); setMapMode(mode); setSection('map') }} />}
      {section === 'recommendation' && data.recommendation && <div className="rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.recommendation')}</h3><p className="mt-2" dir="auto">{isArabic ? data.recommendation.action_ar ?? data.recommendation.action : data.recommendation.action_en ?? data.recommendation.action}</p><p dir="auto">{isArabic ? data.recommendation.summary_ar ?? data.recommendation.summary_en : data.recommendation.summary_en ?? data.recommendation.summary_ar}</p></div>}
      {section === 'recommendation' && operatorControls}
      {section === 'review' && data.review && <div className="space-y-2 rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.review')}</h3><p>{t(`ops.review.${data.review.verdict}`)}</p><p dir="auto">{isArabic ? data.review.summary_ar ?? data.review.summary_en ?? data.review.feedback : data.review.summary_en ?? data.review.summary_ar ?? data.review.feedback}</p><p className="text-xs text-muted-foreground">{t('ops.transition.noSkipToResolved')}</p></div>}
      {section === 'review' && !!data.run?.result?.trace?.length && <ol className="space-y-3">{data.run.result.trace.map(item => <li key={item.iteration} className="space-y-2 rounded-xl border border-border bg-card p-4"><p className="text-xs text-muted-foreground">{t('ops.workspace.reviewRound', { round: item.iteration + 1 })}</p><p className="font-medium">{t(`ops.review.${item.review.verdict}`)}</p><p dir="auto">{isArabic ? item.proposal?.action_ar ?? (item.review.verdict === 'reject' ? t('ops.workspace.rejectedGpsProposal') : item.proposal?.action) : item.proposal?.action_en ?? item.proposal?.action}</p><p className="text-sm text-muted-foreground" dir="auto">{isArabic ? item.review.verdict === 'reject' ? t('ops.workspace.gpsGuard') : t('ops.review.accept') : item.review.feedback}</p></li>)}</ol>}
      {(section === 'overview' || section === 'recommendation') && !!data.decisions?.length && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.human_decision')}</h3>{data.decisions.map((d, i) => <p key={i}>{t(`ops.actions.${d.decision}`)} <time className="text-xs text-muted-foreground" dir="ltr">{d.occurred_at}</time></p>)}</section>}
      {(section === 'overview' || section === 'recommendation') && !!data.executions?.length && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.actionReceipts')}</h3>{data.executions.map((e, i) => <p key={i} className="break-all font-mono text-xs" dir="ltr">{e.receipt_ref}</p>)}<p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p></section>}
      {section === 'diagnosis' && <section className="space-y-3 rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.diagnosis')}</h3>{data.reasoning?.diagnoses?.length ? data.reasoning.diagnoses.map((d, i) => <div key={i}><p className="font-medium">{rootCauseLabel(d.code ?? d.category ?? '')}</p><p dir="auto" className="text-sm text-muted-foreground">{isArabic ? d.summary_ar ?? d.explanation_ar ?? d.explanation_en ?? d.summary : d.summary_en ?? d.explanation_en ?? d.explanation_ar ?? d.summary}</p>{section === 'diagnosis' && <p className="mt-2 break-all font-mono text-xs text-muted-foreground" dir="ltr">{d.evidence_ids?.join(' · ')}</p>}</div>) : <p className="text-sm text-muted-foreground">{t('ops.workspace.noDiagnosis')}</p>}</section>}
      {section === 'diagnosis' && !!data.reasoning?.assessment?.expected_vs_actual?.length && <section className="space-y-3 rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.journey')}</h3>{data.reasoning.assessment.expected_vs_actual.filter(m => m.milestone_id).map(m => <div key={m.milestone_id} className="grid gap-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-3"><p className="break-all font-mono" dir="ltr">{m.milestone_id}</p><p>{t('ops.workspace.expectedBy')} <time dir="ltr">{m.latest_at}</time></p><p>{t(m.missing_due ? 'ops.workspace.missing' : m.late ? 'ops.workspace.late' : 'ops.workspace.observed')} <time dir="ltr">{m.actual_at ?? '—'}</time></p></div>)}</section>}
      {section === 'overview' && state === 'AWAITING_OUTCOME' && caseId && <section className="space-y-3 rounded-xl border border-border p-3">
        <h3 className="font-semibold">{t('ops.actions.observe')}</h3><p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p>
        <div className="flex flex-wrap gap-3"><label>{t('ops.actions.outcomeType')} <select value={outcomeType} onChange={e => setOutcomeType(e.target.value)} className="rounded border border-border bg-card p-2"><option value="">{t('ops.actions.choose')}</option>{['delivery_verified', 'address_corrected', 'barcode_corrected', 'weight_remeasured', 'returned_to_depot', 'dispute_unresolved', 'insufficient_evidence'].map(type => <option key={type} value={type}>{t(`ops.outcomes.${type}`)}</option>)}</select></label><label>{t('ops.actions.observedResult')} <select value={success} onChange={e => setSuccess(e.target.value)} className="rounded border border-border bg-card p-2"><option value="">{t('ops.actions.choose')}</option><option value="true">{t('ops.actions.success')}</option><option value="false">{t('ops.actions.failure')}</option></select></label></div>
        <fieldset className="max-h-48 overflow-y-auto rounded border border-border p-2"><legend className="px-1 text-sm">{t('ops.actions.evidence')}</legend>{data.evidence.nodes.filter(n => ['DeliveryProof', 'AuthenticationEvidence', 'SignatureEvidence', 'PhotoEvidence', 'HandoffEvidence', 'CustodyEvent', 'ScanEvent', 'WeightObservation', 'AddressVersion', 'LocationPin', 'RecipientReport', 'DeliveryAttempt', 'DepotReconciliation'].includes(n.kind)).map(n => <label key={n.id} className="flex items-center gap-2 py-1 text-xs"><input type="checkbox" checked={evidenceIds.includes(n.id)} onChange={e => setEvidenceIds(ids => e.target.checked ? [...ids, n.id] : ids.filter(id => id !== n.id))} /><span dir="ltr" className="min-w-0 break-all">{n.id}</span><span>{entityLabel(n.kind)}</span></label>)}</fieldset>
        <button type="button" disabled={pending || data.state_version == null || !outcomeType || !success || !evidenceIds.length} onClick={() => void command('outcomes', { outcome_type: outcomeType, success: success === 'true', evidence_ids: evidenceIds })} className="rounded-lg border border-border px-3 py-2 disabled:opacity-50">{t('ops.actions.observe')}</button>
      </section>}
      {section === 'overview' && data.outcome && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.outcome')}</h3><p>{t(`ops.actions.${data.outcome.invalidated ? 'invalidated' : data.outcome.verification_status === 'VERIFIED' ? 'verified' : 'observed'}`)}</p><p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p>{state === 'AWAITING_OUTCOME' && !data.outcome.invalidated && data.outcome.verification_status === 'OBSERVED' && (data.outcome.outcome_id ?? data.outcome.id) && <button type="button" disabled={pending || data.state_version == null} onClick={() => void command(`outcomes/${encodeURIComponent(data.outcome!.outcome_id ?? data.outcome!.id!)}/verify`)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-50">{t('ops.actions.verify')}</button>}</section>}
      {section === 'recommendation' && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.proposedActions')}</h3>{data.reasoning?.recommendations?.map((r, i) => <div key={i} dir="auto"><p>{isArabic ? r.action_ar ?? r.action : r.action_en ?? r.action}</p><p className="text-sm text-muted-foreground">{isArabic ? r.explanation_ar ?? r.explanation_en ?? r.rationale : r.explanation_en ?? r.explanation_ar ?? r.rationale}</p></div>)}<p className="text-xs text-muted-foreground">{t('ops.transition.noSkipToResolved')}</p></section>}
      {section === 'map' && <div className="space-y-3"><InvestigationPipeline detail={data} selected={stage} onSelect={inspectStage} onEvidence={() => setSection('evidence')} /><div className="flex flex-wrap items-center gap-2"><div role="group" aria-label={t('explore.lens')} className="flex rounded-lg border border-border bg-card p-0.5">{(['map', 'graph'] as const).map(mode => <button key={mode} type="button" aria-pressed={mapMode === mode} onClick={() => setMapMode(mode)} className={`rounded-md px-3 py-1 text-xs ${mapMode === mode ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}>{t(`explore.${mode}`)}</button>)}</div>{focusIds && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">{t('ops.evidence.focused', { count: focusIds.length })}<button type="button" onClick={() => setFocusIds(null)} className="text-primary underline underline-offset-2">{t('ops.evidence.clearFocus')}</button></p>}</div><div className="h-[calc(100svh-17rem)] min-h-96 overflow-hidden rounded-xl border border-border">{mapMode === 'graph' ? <Graph graph={evidenceGraph(data)} highlightedIds={highlightedIds} /> : <ShipmentRouteMap detail={data} stage={stage} highlightedIds={highlightedIds} />}</div></div>}
      {section === 'history' && <div className="space-y-5">{caseId && <CaseAudit caseId={caseId} />}<section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.similar_cases')}</h3><p className="text-xs text-muted-foreground">{t('ops.outcomeMetrics.syntheticCaution')}</p>{(data.reasoning?.precedents ?? data.precedents ?? []).map((p, i) => <details key={i} className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm"><span className="font-mono" dir="ltr">{p.shipment_id}</span> · {p.success == null ? t('intake.stages.retrieve.pending') : p.success ? t('ops.outcomeMetrics.succeeded') : t('ops.outcomeMetrics.failed')}</summary><p className="mt-2" dir="auto">{isArabic && p.synthetic ? t('ops.workspace.syntheticFollowup') : p.action}</p><time dir="ltr" className="text-xs text-muted-foreground">{p.verified_at}</time><p className="break-all font-mono text-xs text-muted-foreground" dir="ltr">{p.evidence_ids?.join(' · ')}</p></details>)}</section></div>}
    </>}
  </section>
}
