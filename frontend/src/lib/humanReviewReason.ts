import type { Diagnosis, DiagnosisAbsentReason, ShipmentDetail } from '@/contracts/caseDetail'

/** Human-review reasons by the authority rule the routing recorded (run.result.authority.rule_id). */
const BY_RULE: Record<string, string> = {
  'AUTH-02-model-degraded': 'ops.overview.humanReason.modelUnavailable',
  'AUTH-03-reviewer-human': 'ops.overview.humanRequiredJudgment',
  'AUTH-04-contractor-custody': 'ops.overview.humanReason.contractorCustody',
  'AUTH-05-sensitive': 'ops.overview.humanReason.sensitive',
  'AUTH-06-evidence-conflict': 'ops.overview.humanRequired',
  'AUTH-12-human-review-action': 'ops.overview.humanReason.personAction',
  'AUTH-14-symptom-floor': 'ops.overview.humanReason.symptomFloor',
  'AUTH-15-superseded-snapshot': 'ops.overview.humanReason.snapshotSuperseded',
  'AUTH-23-physical-check-requested': 'ops.overview.humanReason.physicalCheck',
}

/**
 * Why a case is with a person, from what the backend actually recorded: the latest outcome or execution
 * when the case came back after an action, else the review and the routing rule. Never a default story.
 */
export function humanReviewReasonKey(detail: ShipmentDetail): string {
  if (detail.workflow_state !== 'HUMAN_REVIEW') return 'ops.overview.evidenceSupported'
  const outcome = detail.outcome
  if (outcome && !outcome.invalidated && outcome.verification_status === 'VERIFIED') {
    if (outcome.success === false) return 'ops.overview.humanReason.verificationFailed'
    if (outcome.exception_cleared === false) return 'ops.overview.humanReason.exceptionRemains'
    return 'ops.overview.humanReason.closureReserved'
  }
  const latest = detail.executions?.[0]  // Served newest first.
  if (latest?.status === 'REFUSED') return 'ops.overview.humanReason.executionRefused'
  if (latest?.status === 'NOT_ACKNOWLEDGED') return 'ops.overview.humanReason.notAcknowledged'
  if (detail.review?.verdict === 'review_unavailable') return 'ops.overview.humanRequiredReview'
  if (detail.review?.reason_code === 'INVESTIGATOR_UNAVAILABLE') return 'ops.overview.humanReason.investigatorUnavailable'
  if (detail.review?.verdict === 'human_review') return 'ops.overview.humanRequiredJudgment'
  return BY_RULE[detail.run?.result?.authority?.rule_id ?? ''] ?? 'ops.overview.humanReason.generic'
}

/** A diagnosis explicitly absent for `reason` (used while a newer run supersedes the fetched one). */
export function absentDiagnosis(reason: DiagnosisAbsentReason, runId: string | null = null): Diagnosis {
  return { available: false, reason, source: null, run_id: runId, superseded_run_id: null, as_of: null, investigated_at: null, primary_cause: null,
    confidence: null, summary: null, hypotheses: [], missing_evidence: [], requires_physical_check: null, tool_calls: 0, snapshot_superseded: false, language: null }
}
