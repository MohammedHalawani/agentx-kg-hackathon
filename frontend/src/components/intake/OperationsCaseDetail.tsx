import { useMemo, useState } from 'react'
import { ActionLifecycle } from '@/components/intake/ActionLifecycle'
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { AskSuhailPanel } from '@/components/operations/AskSuhailPanel'
import { notifyOperator, OperatorToastRegion } from '@/components/operations/OperatorToast'
import { AgentProse } from '@/components/i18n/AgentProse'

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

/** The current run's agent investigation, or why there is none. Rule output never fills it. */
function DiagnosisPanel({ detail }: { detail: ShipmentDetail }) {
  const { t, rootCauseLabel } = useLanguage()
  const d = detail.diagnosis
  return <section data-testid="diagnosis-panel" className="space-y-3 rounded-xl border border-border bg-card p-4">
    <h3 className="font-semibold">{t('ops.diagnosis.title')}</h3>
    {!d?.available ? <p data-testid="diagnosis-absent" className="text-sm text-muted-foreground">{t(`ops.diagnosis.absent.${d?.reason ?? 'not_investigated'}`)}</p> : <>
      <p className="font-medium">{t('ops.diagnosis.primary')}: {rootCauseLabel(d.primary_cause ?? 'UNKNOWN')}</p>
      <p className="text-[11px] text-muted-foreground" dir="auto">{t('ops.diagnosis.provenance', { confidence: d.confidence ?? '—', run: d.run_id ?? '—', at: d.as_of ?? '—' })}</p>
      {d.summary && <p className="text-sm"><AgentProse text={d.summary} /></p>}
      {d.snapshot_superseded && <p className="text-xs text-muted-foreground">{t('ops.diagnosis.snapshotSuperseded')}</p>}
      {d.requires_physical_check && <p className="text-xs text-muted-foreground">{t('ops.diagnosis.physicalCheck')}</p>}
      <h4 className="text-xs font-semibold">{t('ops.diagnosis.hypotheses')}</h4>
      <ul className="space-y-2">{d.hypotheses.map(h => <li key={h.cause} data-testid="diagnosis-hypothesis" className="rounded-lg bg-muted/40 p-2 text-xs">
        <p><span className="font-medium">{rootCauseLabel(h.cause)}</span> · {t(`ops.pipeline.hypothesis.${h.status}`)}</p>
        {h.assessment && <p className="text-muted-foreground"><AgentProse text={h.assessment} /></p>}
        {!!h.supporting_evidence_ids?.length && <p className="break-all font-mono text-muted-foreground" dir="ltr">{t('ops.diagnosis.supporting')}: {h.supporting_evidence_ids.join(' · ')}</p>}
        {!!h.contradicting_evidence_ids?.length && <p className="break-all font-mono text-muted-foreground" dir="ltr">{t('ops.diagnosis.contradicting')}: {h.contradicting_evidence_ids.join(' · ')}</p>}
      </li>)}</ul>
      {!!d.missing_evidence.length && <><h4 className="text-xs font-semibold">{t('ops.diagnosis.missing')}</h4><ul className="list-disc ps-5 text-xs">{d.missing_evidence.map((m, i) => <li key={i}><AgentProse text={m} /></li>)}</ul></>}
    </>}
  </section>
}

/** Deterministic rule checks at their own as-of time, labelled as signals, never as the diagnosis. */
function RuleSignalsPanel({ detail }: { detail: ShipmentDetail }) {
  const { t, isArabic, rootCauseLabel } = useLanguage()
  const r = detail.rule_signals
  if (!r) return null
  return <section data-testid="rule-signals-panel" className="space-y-2 rounded-xl border border-dashed border-border p-4">
    <h3 className="text-sm font-semibold">{t('ops.ruleSignals.title')}</h3>
    <p className="text-[11px] text-muted-foreground">{t('ops.ruleSignals.hint')} · {t('ops.ruleSignals.asOf')} <time dir="ltr">{r.as_of}</time></p>
    {r.signals.length ? r.signals.map(sig => <div key={sig.code} className="text-xs"><p className="font-medium">{rootCauseLabel(sig.code)}</p><p dir="auto" className="text-muted-foreground">{isArabic ? sig.summary_ar ?? sig.summary_en : sig.summary_en}</p>{!!sig.evidence_ids?.length && <p className="break-all font-mono text-muted-foreground" dir="ltr">{sig.evidence_ids.join(' · ')}</p>}</div>) : <p className="text-xs text-muted-foreground">{t('ops.ruleSignals.none')}</p>}
  </section>
}

export function OperationsCaseDetail({ caseId, shipmentId, onBack }: { caseId?: string; shipmentId: string; onBack: () => void }) {
  const { t, isArabic } = useLanguage()
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
  const [section, setSection] = useState<Section>('overview')
  const [mapMode, setMapMode] = useState<'map' | 'graph'>('map')
  // Fresh evidence assessment is a proposal, never the mutable workflow authority.
  const state = data?.workflow_state
  const toastFor = (action: string, body: Record<string, unknown>) => {
    if (action === 'decision' && body.decision === 'reopen') return t('ops.toast.reopened')
    if (action === 'decision') return t('ops.toast.decisionRecorded')
    if (action === 'reanalyze') return t('ops.toast.reanalyzeQueued')
    if (action === 'outcomes') return t('ops.toast.verificationRequested')
    if (action === 'human-outcome') return t('ops.toast.humanOutcomeRecorded')
    return t('ops.toast.actionRecorded')
  }
  const command = async (action: string, body: Record<string, unknown> = {}) => {
    if (!caseId || pending) return
    setPending(true); setActionError(null)
    try {
      await operationsPost(`/cases/${encodeURIComponent(caseId)}/${action}`, { ...body, idempotency_key: crypto.randomUUID(), expected_version: data?.state_version })
      notifyOperator(toastFor(action, body))
      refetch()
    }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Request failed') }
    finally { setPending(false) }
  }
  const terminal = state === 'RESOLVED' || state === 'REJECTED' || state === 'ESCALATED'
  const operatorControls = data && (caseId && (state === 'AWAITING_APPROVAL' || state === 'HUMAN_REVIEW') && <section className="space-y-1 border-t border-border pt-2" aria-label={t('ops.automation.humanDecision')}><h4 className="text-xs font-semibold">{t('ops.automation.humanDecision')}</h4><p className="text-[11px] leading-4 text-muted-foreground">{t(state === 'HUMAN_REVIEW' ? 'ops.automation.humanReason' : 'ops.automation.authorizationReason')}</p><div className="flex flex-wrap gap-2">{(['approve', 'reject', 'request_evidence', 'escalate'] as const).map(decision => <button key={decision} type="button" disabled={pending || data.state_version == null || (decision === 'approve' && (!data.recommendation_id || !data.recommendation || data.recommendation.approvable === false))} onClick={() => void command('decision', { decision })} className="rounded-lg border border-border bg-card px-2 py-1 text-xs disabled:opacity-50">{t(`ops.actions.${decision}`)}</button>)}<button type="button" disabled={pending} onClick={() => void command('reanalyze')} className="text-[11px] text-muted-foreground underline underline-offset-2">{t('ops.actions.reanalyze')}</button></div>{data.recommendation?.approvable === false && <p data-testid="approval-blocked" className="text-[11px] text-muted-foreground">{t(data.recommendation.approval_rule === 'AUTH-12-human-review-action' ? 'ops.actions.personOnly' : 'ops.actions.neverExecuted')}</p>}</section>)
  return <section className="mx-auto max-w-[1600px] space-y-3" dir={isArabic ? 'rtl' : 'ltr'}>
    <OperatorToastRegion />
    <header className="flex flex-wrap items-center gap-2 border-b border-border pb-2">
      <Button type="button" variant="outline" size="xs" onClick={onBack}>{t('ops.workspace.back')}</Button>
      <div className="min-w-0">
        <h2 className="font-mono text-base leading-tight" dir="ltr">{data?.shipment_id || shipmentId}</h2>
        {caseId && <p className="font-mono text-[10px] text-muted-foreground" dir="ltr">{t('ops.workspace.caseRef', { id: caseId })}</p>}
      </div>
      {state && <CaseWorkflowBadge state={state} />}
      {state && !terminal && <span className="text-[10px] text-muted-foreground">{t('ops.workspace.notClosed')}</span>}
      {data?.priority && <span className="text-[10px] text-muted-foreground">{t(`ops.priority.${data.priority}`)}</span>}
      {data?.synthetic && <span className="text-[10px] text-muted-foreground">{t('ops.simulation.label')}</span>}
      <div className="ms-auto flex flex-wrap items-center gap-1.5">
        {caseId && terminal && data?.state_version != null && (
          <Button type="button" variant="outline" size="xs" disabled={pending} onClick={() => void command('decision', { decision: 'reopen' })}>{t('ops.actions.reopen')}</Button>
        )}
        <Button type="button" variant="outline" size="xs" disabled={pending || loading} onClick={refetch}>{t('explore.refresh')}</Button>
      </div>
    </header>
    {loading && !data ? <LoadingState label={t('explore.loading')} /> : error || (data && !data.evidence?.nodes) ? <ErrorState onRetry={refetch} /> : data && <>
      {caseId && (state === 'OPEN' || state === 'REOPENED' || state === 'INVESTIGATING') && <p role="status" className="text-[11px] leading-4 text-muted-foreground">{t(state === 'INVESTIGATING' ? 'ops.automation.processing' : 'ops.automation.queued')}</p>}
      {!caseId && <p className="text-sm text-muted-foreground">{t('ops.workspace.evidenceOnly')}</p>}
      {actionError && <ErrorState message={t('ops.error.action')} onRetry={() => { setActionError(null); refetch() }} />}
      <Tabs value={section} onValueChange={(v) => setSection(v as Section)}>
        <TabsList aria-label={t('ops.workspace.sections')}>
          {SECTIONS.map(key => <TabsTrigger key={key} value={key}>{t(`ops.workspace.${key}`)}</TabsTrigger>)}
        </TabsList>
      </Tabs>
      {unavailable && <p role="status" className="text-xs text-muted-foreground">{t('ops.pipeline.disconnected')}</p>}
      {section === 'overview' && <>
        <CaseOverview detail={data} stage={stage} highlightedIds={highlightedIds} onStage={inspectStage} actions={operatorControls} onDeepDive={(target, mode) => { setSection(target); if(mode) setMapMode(mode) }} />
        <AskSuhailPanel detail={data} caseId={caseId} />
      </>}
      {section === 'evidence' && <CaseEvidence detail={data} onHistory={() => setSection('history')} onShow={(ids, mode) => { setFocusIds(ids); setMapMode(mode); setSection('map') }} />}
      {section === 'recommendation' && data.recommendation && <div className="rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.recommendation')}</h3><p className="mt-2" dir="auto">{isArabic ? data.recommendation.action_ar ?? data.recommendation.action : data.recommendation.action_en ?? data.recommendation.action}</p><p dir="auto">{isArabic ? data.recommendation.summary_ar ?? data.recommendation.summary_en : data.recommendation.summary_en ?? data.recommendation.summary_ar}</p></div>}
      {section === 'recommendation' && operatorControls}
      {section === 'review' && data.review && <div className="space-y-2 rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.review')}</h3><p>{t(`ops.review.${data.review.verdict}`)}</p><p dir="auto">{isArabic ? data.review.summary_ar ?? data.review.summary_en ?? data.review.feedback : data.review.summary_en ?? data.review.summary_ar ?? data.review.feedback}</p><p className="text-xs text-muted-foreground">{t('ops.transition.noSkipToResolved')}</p></div>}
      {section === 'review' && !!data.run?.result?.trace?.length && <ol className="space-y-3">{data.run.result.trace.map(item => <li key={item.iteration} className="space-y-2 rounded-xl border border-border bg-card p-4"><p className="text-xs text-muted-foreground">{t('ops.workspace.reviewRound', { round: item.iteration + 1 })}</p><p className="font-medium">{t(`ops.review.${item.review.verdict}`)}</p>{item.proposal && <p dir="auto">{isArabic ? item.proposal.action_ar ?? item.proposal.action_en ?? item.proposal.action : item.proposal.action_en ?? item.proposal.action}</p>}<p data-testid="review-round-reason" className="text-sm text-muted-foreground" dir="auto">{isArabic ? item.review.summary_ar ?? item.review.feedback : item.review.feedback}</p></li>)}</ol>}
      {(section === 'overview' || section === 'recommendation') && !!data.decisions?.length && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.human_decision')}</h3>{data.decisions.map((d, i) => <p key={i}>{t(`ops.actions.${d.decision}`)} <time className="text-xs text-muted-foreground" dir="ltr">{d.occurred_at}</time></p>)}</section>}
      {section === 'diagnosis' && <DiagnosisPanel detail={data} />}
      {section === 'diagnosis' && <RuleSignalsPanel detail={data} />}
      {section === 'diagnosis' && !!data.rule_signals?.expected_vs_actual?.length && <section className="space-y-3 rounded-xl border border-border bg-card p-4"><h3 className="font-semibold">{t('ops.workspace.journey')}</h3><p className="text-xs text-muted-foreground">{t('ops.ruleSignals.asOf')} <time dir="ltr">{data.rule_signals.as_of}</time></p>{data.rule_signals.expected_vs_actual.filter(m => m.milestone_id).map(m => <div key={m.milestone_id} className="grid gap-2 rounded-lg bg-muted/40 p-3 text-xs sm:grid-cols-3"><p className="break-all font-mono" dir="ltr">{m.milestone_id}</p><p>{t('ops.workspace.expectedBy')} <time dir="ltr">{m.latest_at}</time></p><p>{t(m.missing_due ? 'ops.workspace.missing' : m.late ? 'ops.workspace.late' : 'ops.workspace.observed')} <time dir="ltr">{m.actual_at ?? '—'}</time></p></div>)}</section>}
      {section === 'overview' && <ActionLifecycle detail={data} command={command} pending={pending} />}
      {section === 'map' && <div className="space-y-3"><InvestigationPipeline detail={data} selected={stage} onSelect={inspectStage} onEvidence={() => setSection('evidence')} /><div className="flex flex-wrap items-center gap-2"><div role="group" aria-label={t('explore.lens')} className="inline-flex rounded-lg border border-border bg-card p-0.5">{(['map', 'graph'] as const).map(mode => <Button key={mode} type="button" size="xs" variant={mapMode === mode ? 'default' : 'ghost'} aria-pressed={mapMode === mode} onClick={() => setMapMode(mode)}>{t(`explore.${mode}`)}</Button>)}</div>{focusIds && <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">{t('ops.evidence.focused', { count: focusIds.length })}<button type="button" onClick={() => setFocusIds(null)} className="text-primary underline underline-offset-2">{t('ops.evidence.clearFocus')}</button></p>}</div><div className="h-[calc(100svh-17rem)] min-h-96 overflow-hidden rounded-xl border border-border" data-map-mode={mapMode}>{mapMode === 'graph' ? <Graph graph={evidenceGraph(data)} highlightedIds={highlightedIds} viewportKey={mapMode} /> : <ShipmentRouteMap key={mapMode} detail={data} stage={stage} highlightedIds={highlightedIds} />}</div></div>}
      {section === 'history' && <div className="space-y-5">{caseId && <CaseAudit caseId={caseId} />}<section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.similar_cases')}</h3><p className="text-xs text-muted-foreground">{t('ops.outcomeMetrics.syntheticCaution')}</p>{(data.rule_signals?.precedents ?? data.precedents ?? []).map((p, i) => <details key={i} className="rounded-lg border border-border p-3"><summary className="cursor-pointer text-sm"><span className="font-mono" dir="ltr">{p.shipment_id}</span> · {p.success == null ? t('intake.stages.retrieve.pending') : p.success ? t('ops.outcomeMetrics.succeeded') : t('ops.outcomeMetrics.failed')}</summary><p className="mt-2" dir="auto">{isArabic && p.synthetic ? t('ops.workspace.syntheticFollowup') : p.action}</p><time dir="ltr" className="text-xs text-muted-foreground">{p.verified_at}</time><p className="break-all font-mono text-xs text-muted-foreground" dir="ltr">{p.evidence_ids?.join(' · ')}</p></details>)}</section></div>}
    </>}
  </section>
}
