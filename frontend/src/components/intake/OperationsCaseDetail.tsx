import { useState } from 'react'
import { useFetch } from '@/hooks/useFetch'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { operationsPost } from '@/lib/operationsClient'
import type { ShipmentDetail } from '@/contracts/caseDetail'
import { evidenceGraph } from '@/contracts/caseDetail'
import { Graph } from '@/components/artifacts/Graph'
import { CaseWorkflowBadge } from '@/components/operations/StatusBadge'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'

export function OperationsCaseDetail({ caseId, shipmentId, onBack }: { caseId?: string; shipmentId: string; onBack: () => void }) {
  const { t, isArabic, rootCauseLabel, entityLabel } = useLanguage()
  const { data, loading, error, refetch } = useFetch<ShipmentDetail>(caseId ? `/cases/${encodeURIComponent(caseId)}` : `/shipments/${encodeURIComponent(shipmentId)}/context`)
  const [pending, setPending] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [outcomeType, setOutcomeType] = useState('')
  const [success, setSuccess] = useState('')
  const [evidenceIds, setEvidenceIds] = useState<string[]>([])
  // Fresh evidence assessment is a proposal, never the mutable workflow authority.
  const state = data?.workflow_state
  const command = async (action: string, body: Record<string, unknown> = {}) => {
    if (!caseId || pending) return
    setPending(true); setActionError(null)
    try { await operationsPost(`/cases/${encodeURIComponent(caseId)}/${action}`, { ...body, idempotency_key: crypto.randomUUID(), expected_version: data?.state_version }); refetch() }
    catch (e) { setActionError(e instanceof Error ? e.message : 'Request failed') }
    finally { setPending(false) }
  }
  return <section className="mx-auto max-w-6xl space-y-4" dir={isArabic ? 'rtl' : 'ltr'}>
    <button type="button" onClick={onBack} className="rounded-lg border border-border px-3 py-2">{t('ops.workspace.back')}</button>
    <button type="button" disabled={pending || loading} onClick={refetch} className="ms-2 rounded-lg border border-border px-3 py-2 disabled:opacity-50">{t('explore.refresh')}</button>
    <h2 className="font-mono text-lg" dir="ltr">{shipmentId}</h2>
    {loading ? <LoadingState label={t('explore.loading')} /> : error ? <ErrorState onRetry={refetch} /> : data && <>
      {data.synthetic && <p className="text-xs font-semibold text-chart-warning">{t('ops.simulation.label')}</p>}
      {state && <CaseWorkflowBadge state={state} />}
      {caseId && (state === 'OPEN' || state === 'REOPENED') ? <button type="button" disabled={pending || data.state_version == null} onClick={() => void command('investigate')} className="rounded-lg bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50">{t('ops.case.openInvestigation')}</button> : <p className="text-sm text-muted-foreground">{t('ops.workspace.evidenceOnly')}</p>}
      {caseId && (state === 'AWAITING_APPROVAL' || state === 'HUMAN_REVIEW') && <div className="flex flex-wrap gap-2">{(['approve', 'reject', 'request_evidence', 'escalate'] as const).map(decision => <button key={decision} type="button" disabled={pending || data.state_version == null || (decision === 'approve' && !data.recommendation_id)} onClick={() => void command('decision', { decision })} className="rounded-lg border border-border bg-card px-3 py-2 disabled:opacity-50">{t(`ops.actions.${decision}`)}</button>)}</div>}
      {actionError && <ErrorState message={t('ops.error.action')} onRetry={() => { setActionError(null); refetch() }} />}
      {data.recommendation && <div className="rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.recommendation')}</h3><p dir="auto">{isArabic ? data.recommendation.action_ar ?? data.recommendation.action : data.recommendation.action_en ?? data.recommendation.action}</p><p dir="auto">{isArabic ? data.recommendation.summary_ar ?? data.recommendation.summary_en : data.recommendation.summary_en ?? data.recommendation.summary_ar}</p></div>}
      {data.review && <div className="rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.review')}</h3><p>{data.review.verdict}</p><p dir="auto">{isArabic ? data.review.summary_ar ?? data.review.summary_en ?? data.review.feedback : data.review.summary_en ?? data.review.summary_ar ?? data.review.feedback}</p></div>}
      {!!data.decisions?.length && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.human_decision')}</h3>{data.decisions.map((d, i) => <p key={i}>{t(`ops.actions.${d.decision}`)} <time className="text-xs text-muted-foreground" dir="ltr">{d.occurred_at}</time></p>)}</section>}
      {!!data.executions?.length && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.actionReceipts')}</h3>{data.executions.map((e, i) => <p key={i} className="break-all font-mono text-xs" dir="ltr">{e.receipt_ref}</p>)}<p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p></section>}
      <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.diagnosis')}</h3>{data.reasoning?.diagnoses?.map((d, i) => <div key={i}><p>{rootCauseLabel(d.code ?? d.category ?? '')}</p><p dir="auto" className="text-sm text-muted-foreground">{isArabic ? d.summary_ar ?? d.explanation_ar ?? d.explanation_en ?? d.summary : d.summary_en ?? d.explanation_en ?? d.explanation_ar ?? d.summary}</p><p className="break-all font-mono text-xs" dir="ltr">{d.evidence_ids?.join(' · ')}</p></div>)}</section>
      {state === 'AWAITING_OUTCOME' && caseId && <section className="space-y-3 rounded-xl border border-border p-3">
        <h3 className="font-semibold">{t('ops.actions.observe')}</h3><p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p>
        <div className="flex flex-wrap gap-3"><label>{t('ops.actions.outcomeType')} <select value={outcomeType} onChange={e => setOutcomeType(e.target.value)} className="rounded border border-border bg-card p-2"><option value="">{t('ops.actions.choose')}</option>{['delivery_verified', 'address_corrected', 'barcode_corrected', 'weight_remeasured', 'returned_to_depot', 'dispute_unresolved', 'insufficient_evidence'].map(type => <option key={type} value={type}>{t(`ops.outcomes.${type}`)}</option>)}</select></label><label>{t('ops.actions.observedResult')} <select value={success} onChange={e => setSuccess(e.target.value)} className="rounded border border-border bg-card p-2"><option value="">{t('ops.actions.choose')}</option><option value="true">{t('ops.actions.success')}</option><option value="false">{t('ops.actions.failure')}</option></select></label></div>
        <fieldset className="max-h-48 overflow-y-auto rounded border border-border p-2"><legend className="px-1 text-sm">{t('ops.actions.evidence')}</legend>{data.evidence.nodes.filter(n => ['DeliveryProof', 'AuthenticationEvidence', 'SignatureEvidence', 'PhotoEvidence', 'HandoffEvidence', 'CustodyEvent', 'ScanEvent', 'WeightObservation', 'AddressVersion', 'LocationPin', 'RecipientReport', 'DeliveryAttempt', 'DepotReconciliation'].includes(n.kind)).map(n => <label key={n.id} className="flex items-center gap-2 py-1 text-xs"><input type="checkbox" checked={evidenceIds.includes(n.id)} onChange={e => setEvidenceIds(ids => e.target.checked ? [...ids, n.id] : ids.filter(id => id !== n.id))} /><span dir="ltr" className="min-w-0 break-all">{n.id}</span><span>{entityLabel(n.kind)}</span></label>)}</fieldset>
        <button type="button" disabled={pending || data.state_version == null || !outcomeType || !success || !evidenceIds.length} onClick={() => void command('outcomes', { outcome_type: outcomeType, success: success === 'true', evidence_ids: evidenceIds })} className="rounded-lg border border-border px-3 py-2 disabled:opacity-50">{t('ops.actions.observe')}</button>
      </section>}
      {data.outcome && <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.trace.outcome')}</h3><p>{t(`ops.actions.${data.outcome.invalidated ? 'invalidated' : data.outcome.verification_status === 'VERIFIED' ? 'verified' : 'observed'}`)}</p><p className="text-xs text-muted-foreground">{t('ops.actions.outcomeHint')}</p>{state === 'AWAITING_OUTCOME' && !data.outcome.invalidated && data.outcome.verification_status === 'OBSERVED' && (data.outcome.outcome_id ?? data.outcome.id) && <button type="button" disabled={pending || data.state_version == null} onClick={() => void command(`outcomes/${encodeURIComponent(data.outcome!.outcome_id ?? data.outcome!.id!)}/verify`)} className="rounded-lg border border-border px-3 py-2 disabled:opacity-50">{t('ops.actions.verify')}</button>}</section>}
      <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.proposedActions')}</h3>{data.reasoning?.recommendations?.map((r, i) => <div key={i} dir="auto"><p>{isArabic ? r.action_ar ?? r.action : r.action_en ?? r.action}</p><p className="text-sm text-muted-foreground">{isArabic ? r.explanation_ar ?? r.explanation_en ?? r.rationale : r.explanation_en ?? r.explanation_ar ?? r.rationale}</p></div>)}<p className="text-xs text-muted-foreground">{t('ops.transition.noSkipToResolved')}</p></section>
      <div className="h-[480px] min-h-80 overflow-hidden rounded-xl border border-border"><Graph graph={evidenceGraph(data)} /></div>
      <section className="space-y-2 rounded-xl border border-border p-3"><h3 className="font-semibold">{t('ops.workspace.history')}</h3><p className="text-xs text-muted-foreground">{t('ops.outcomeMetrics.syntheticCaution')}</p>{(data.reasoning?.precedents ?? data.precedents ?? []).map((p, i) => <div key={i} className="rounded-lg border border-border p-2"><p className="break-all font-mono text-xs" dir="ltr">{p.shipment_id}</p><p dir="auto">{p.action}</p><p className="text-xs">{p.success == null ? t('intake.stages.retrieve.pending') : p.success ? t('ops.outcomeMetrics.succeeded') : t('ops.outcomeMetrics.failed')}</p><time dir="ltr" className="text-xs text-muted-foreground">{p.verified_at}</time><p className="break-all font-mono text-xs text-muted-foreground" dir="ltr">{p.evidence_ids?.join(' · ')}</p></div>)}</section>
    </>}
  </section>
}
