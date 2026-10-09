import type { AuditEvent, CasePriority, CaseWorkflowState, OperationsCase, OperationalShipmentStatus, QueueBucketCounts, TimeRangePreset } from '@/contracts/operations'

export interface ApiPage<T> {
  items: T[]
  filtered_total: number
  next_cursor: string | null
  previous_cursor: string | null
  metadata?: { buckets?: Record<string, number>; filter_choices?: Record<string, string[]>; offset?: number; as_of?: string; split?: string }
}
export interface ApiCase {
  case_id: string; shipment_id: string; issue_summary: string; city?: string; category?: string
  priority: CasePriority; workflow_state: CaseWorkflowState; operational_status?: OperationalShipmentStatus
  opened_at?: string; synthetic?: boolean
}
export function adaptCase(row: ApiCase): OperationsCase {
  return { caseId: row.case_id, shipmentId: row.shipment_id, issueSummary: row.issue_summary, city: row.city, category: row.category, priority: row.priority, workflowState: row.workflow_state, operationalStatus: row.operational_status, openedAt: row.opened_at }
}
export interface ApiAuditEvent {
  id: string; timestamp: string; shipment_id: string; case_id?: string; event_type: string; actor: string; model?: string; decision?: string; result?: string; synthetic?: boolean; stage?:string; stage_status?:string
}
export function adaptAudit(row: ApiAuditEvent): AuditEvent {
  return { id: row.id, timestamp: row.timestamp, shipmentId: row.shipment_id, caseId: row.case_id, eventType: row.event_type as AuditEvent['eventType'], actor: row.actor, model: row.model, decision: row.decision, result: row.result, stage:row.stage,stageStatus:row.stage_status }
}
export function adaptBuckets(b: Record<string, number> = {}): QueueBucketCounts {
  return { open: (b.OPEN ?? b.open ?? 0) + (b.REOPENED ?? 0), investigating: b.INVESTIGATING ?? b.investigating ?? 0, needsReview: b.HUMAN_REVIEW ?? b.needs_review ?? 0, needsEvidence: b.NEEDS_EVIDENCE ?? 0, awaitingApproval: b.AWAITING_APPROVAL ?? b.awaiting_approval ?? 0, awaitingOutcome: b.AWAITING_OUTCOME ?? b.awaiting_outcome ?? 0, resolved: b.RESOLVED ?? b.resolved ?? 0 }
}
export function pageQuery(values: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value != null && value !== '' && value !== 'all') p.set(key, String(value))
  return p.toString()
}
// Dataset clocks can differ from wall time. Use the server snapshot when available.
export function dateBounds(preset: TimeRangePreset | 'all', asOf?: string, customFrom?: string, customTo?: string): { from?: string; to?: string } {
  if (preset === 'all') return {}
  if (preset === 'custom') return { from: customFrom ? new Date(`${customFrom}T00:00:00Z`).toISOString() : undefined, to: customTo ? new Date(`${customTo}T23:59:59.999Z`).toISOString() : undefined }
  const end = new Date(asOf ?? Date.now())
  if (!Number.isFinite(end.getTime())) return {}
  const start = new Date(end)
  if (preset === 'today') start.setUTCHours(0, 0, 0, 0)
  else start.setTime(end.getTime() - ({ '24h': 1, week: 7, month: 30 }[preset] * 86400000))
  return { from: start.toISOString(), to: end.toISOString() }
}
