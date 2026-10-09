import { useState } from 'react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { ShipmentDetail } from '@/contracts/caseDetail'

/**
 * Authorized → executed with receipt → verification pending → verified / verification failed,
 * and the human-investigation path. Every state shown is a recorded backend record; the operator can
 * ask the verifier to check now but cannot declare success. A person closes a human-investigation case
 * only by recording a finding with attached evidence (HUMAN_VERIFIED, kept apart from evidence-verified).
 */
export type Command = (action: string, body?: Record<string, unknown>) => Promise<void>

const HUMAN_OUTCOMES = ['parcel_located', 'delivered_confirmed_by_person', 'returned_to_depot', 'data_corrected', 'parcel_not_found'] as const

export function lifecycleStage(detail: ShipmentDetail): string | null {
  const execution = detail.executions?.[0]
  const outcome = detail.outcome
  // A person's finding closes the case only when it resolves it; 'parcel not found' escalates and stays open.
  if (outcome && !outcome.invalidated && outcome.verification_status === 'HUMAN_VERIFIED') return outcome.success ? 'human_verified' : 'human_escalated'
  if (outcome && !outcome.invalidated && outcome.verification_status === 'VERIFIED') {
    // The action did what it was meant to, but the exception is still there: not resolved.
    if (outcome.success && outcome.exception_cleared === false) return 'exception_remains'
    return outcome.success ? 'verified' : 'verification_failed'
  }
  if (!execution) return detail.workflow_state === 'HUMAN_REVIEW' ? 'human_investigation' : null
  if (execution.status === 'AUTHORIZED' || execution.status === 'EXECUTING') return 'authorized'
  if (execution.status === 'ACKNOWLEDGED') return 'verification_pending'
  return null
}

export function ActionLifecycle({ detail, command, pending }: { detail: ShipmentDetail; command: Command; pending: boolean }) {
  const { t, entityLabel } = useLanguage()
  const [outcomeType, setOutcomeType] = useState('')
  const [finding, setFinding] = useState('')
  const [evidenceIds, setEvidenceIds] = useState<string[]>([])
  const stage = lifecycleStage(detail)
  const state = detail.workflow_state
  const execution = detail.executions?.[0]
  const outcome = detail.outcome
  const humanOpen = state === 'HUMAN_REVIEW' || state === 'ESCALATED' || state === 'NEEDS_EVIDENCE'
  if (!stage && !humanOpen) return null
  const adapter = (() => { try { return JSON.parse(execution?.adapter_result_json ?? '{}') as { behaviour?: string } } catch { return {} } })()
  return <section data-testid="action-lifecycle" data-lifecycle={stage ?? 'human_investigation'} className="space-y-2 rounded-xl border border-border p-3">
    <h3 className="font-semibold">{t('ops.lifecycle.title')}</h3>
    {stage && <p className="text-sm font-medium">{t(`ops.lifecycle.${stage}`)}</p>}
    {execution && <dl className="grid gap-x-3 gap-y-1 text-xs sm:grid-cols-2">
      <dt className="text-muted-foreground">{t('ops.lifecycle.action')}</dt><dd className="font-mono" dir="ltr">{execution.action_type}</dd>
      <dt className="text-muted-foreground">{t('ops.lifecycle.authority')}</dt><dd>{t(`ops.lifecycle.by.${execution.authority === 'AUTO_POLICY' ? 'policy' : 'operator'}`)}</dd>
      {execution.receipt_ref && <><dt className="text-muted-foreground">{t('ops.lifecycle.receipt')}</dt><dd className="break-all font-mono" dir="ltr">{execution.receipt_ref}</dd></>}
      {adapter.behaviour && <><dt className="text-muted-foreground">{t('ops.lifecycle.fieldResponse')}</dt><dd dir="auto">{adapter.behaviour}</dd></>}
      {execution.deadline_at && <><dt className="text-muted-foreground">{t('ops.lifecycle.deadline')}</dt><dd dir="ltr">{execution.deadline_at}</dd></>}
      {execution.closure === 'HUMAN' && <><dt className="text-muted-foreground">{t('ops.lifecycle.closure')}</dt><dd>{t('ops.lifecycle.closureHuman')}</dd></>}
    </dl>}
    {outcome && <p className="text-xs text-muted-foreground" dir="auto">{t(outcome.verification_status === 'HUMAN_VERIFIED' ? 'ops.lifecycle.recordedBy' : 'ops.lifecycle.verifier')} · <span className="font-mono" dir="ltr">{outcome.verification_status === 'HUMAN_VERIFIED' ? outcome.verifier_id : outcome.rule_id ?? outcome.outcome_type}</span>{outcome.reason ? ` · ${outcome.reason}` : ''}</p>}
    {stage === 'exception_remains' && !!outcome?.remaining_symptoms?.length && <p className="text-xs">{t('ops.lifecycle.remaining')} {outcome.remaining_symptoms.map(code => t(`symptoms.${code}`)).join(' · ')}</p>}
    {execution && <p className="text-xs text-muted-foreground">{t('ops.lifecycle.rule')}</p>}
    {state === 'AWAITING_OUTCOME' && <button type="button" disabled={pending || detail.state_version == null} onClick={() => void command('outcomes')}
      className="rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-50">{t('ops.lifecycle.checkNow')}</button>}
    {humanOpen && <form className="space-y-2 border-t border-border pt-2" onSubmit={e => { e.preventDefault(); void command('human-outcome', { outcome_type: outcomeType, finding, evidence_ids: evidenceIds }) }}>
      <h4 className="text-xs font-semibold">{t('ops.lifecycle.humanTitle')}</h4>
      <p className="text-[11px] text-muted-foreground">{t('ops.lifecycle.humanHint')}</p>
      <select aria-label={t('ops.lifecycle.humanOutcome')} value={outcomeType} onChange={e => setOutcomeType(e.target.value)} className="rounded border border-border bg-card p-1.5 text-xs">
        <option value="">{t('ops.actions.choose')}</option>
        {HUMAN_OUTCOMES.map(o => <option key={o} value={o}>{t(`ops.lifecycle.human.${o}`)}</option>)}
      </select>
      <textarea aria-label={t('ops.lifecycle.finding')} value={finding} onChange={e => setFinding(e.target.value)} rows={2} dir="auto"
        placeholder={t('ops.lifecycle.findingPlaceholder')} className="w-full rounded border border-border bg-card p-2 text-xs" />
      <fieldset className="max-h-40 overflow-y-auto rounded border border-border p-2"><legend className="px-1 text-xs">{t('ops.actions.evidence')}</legend>
        {detail.evidence.nodes.filter(n => !['Shipment', 'City', 'Policy', 'ServiceLevel', 'VehicleType', 'ShipmentType', 'HandlingRequirement'].includes(n.kind)).slice(0, 80).map(n =>
          <label key={n.id} className="flex items-center gap-2 py-0.5 text-xs"><input type="checkbox" checked={evidenceIds.includes(n.id)} onChange={e => setEvidenceIds(ids => e.target.checked ? [...ids, n.id] : ids.filter(id => id !== n.id))} /><span dir="ltr" className="min-w-0 break-all">{n.id}</span><span>{entityLabel(n.kind)}</span></label>)}
      </fieldset>
      <button type="submit" disabled={pending || !outcomeType || finding.trim().length < 10 || !evidenceIds.length} className="rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-50">{t('ops.lifecycle.recordHuman')}</button>
    </form>}
  </section>
}
