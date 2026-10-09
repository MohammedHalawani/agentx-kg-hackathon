/** UI contracts for Suhail Operations V2. Optional fields stay optional — adapters fill from V1 APIs. */

export type OperationalShipmentStatus =
  | 'ON_TIME'
  | 'NEEDS_ATTENTION'
  | 'SLA_RISK'
  | 'CRITICAL'
  | 'UNRECONCILED_CUSTODY'
  | 'DELIVERY_DISPUTE'
  | 'ADDRESS_CONFLICT'
  | 'RECIPIENT_UNAVAILABLE'
  | 'HUB_DELAY'
  | 'RESOLVED'

export type CaseWorkflowState =
  | 'OPEN'
  | 'INVESTIGATING'
  | 'NEEDS_EVIDENCE'
  | 'RECOMMENDATION_READY'
  | 'AWAITING_APPROVAL'
  | 'ACTION_INITIATED'
  | 'REJECTED'
  | 'HUMAN_REVIEW'
  | 'AWAITING_OUTCOME'
  | 'ESCALATED'
  | 'REOPENED'
  | 'RESOLVED'

export type CasePriority = 'low' | 'medium' | 'high' | 'unknown'

export type TimeRangePreset = 'today' | '24h' | 'week' | 'month' | 'custom'

export interface PaginatedRequest {
  cursor?: string | null
  limit: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  nextCursor: string | null
  prevCursor: string | null
}

export interface OperationsCase {
  caseId: string
  shipmentId: string
  issueSummary: string
  city?: string | null
  courier?: string | null
  category?: string | null
  /** Observable symptoms the monitor detected; the cause is unknown until investigated. */
  symptoms?: string[]
  priority: CasePriority
  workflowState: CaseWorkflowState
  operationalStatus?: OperationalShipmentStatus | null
  openedAt?: string | null
  durationLabel?: string | null
  /** Original complaint text for pipeline run (V1). */
  runText?: string
}

export interface QueueBucketCounts {
  open: number
  investigating: number
  needsReview: number
  needsEvidence?: number
  awaitingApproval: number
  awaitingOutcome: number
  resolved: number
  /** Human review + approval + evidence + escalated. */
  human?: number
}

export interface IntakeFilters {
  search: string
  timePreset: TimeRangePreset | 'all'
  priority: CasePriority | 'all'
  city: string | 'all'
  status: CaseWorkflowState | 'all'
  cause: string | 'all'
}

export type AuditEventType =
  | 'exception_opened'
  | 'investigation_started'
  | 'evidence_collected'
  | 'needs_review'
  | 'recommendation_ready'
  | 'outcome_confirmed'
  | 'resolved'
  | 'escalated'
  | 'pipeline_error'

export interface AuditEvent {
  id: string
  timestamp: string
  shipmentId: string
  caseId?: string | null
  eventType: AuditEventType
  actor: string
  model?: string | null
  decision?: string | null
  result?: string | null
  stage?: string
  stageStatus?: string
  /** When true, row comes from demo fixtures — not live backend. */
  fixture?: boolean
}

export interface AgentTraceStep {
  id: string
  kind:
    | 'evidence'
    | 'similar_cases'
    | 'hypothesis'
    | 'recommendation'
    | 'safety_review'
    | 'human_decision'
    | 'outcome'
  titleKey: string
  summary?: string
  status: 'pending' | 'active' | 'complete' | 'skipped'
  detail?: string
}
