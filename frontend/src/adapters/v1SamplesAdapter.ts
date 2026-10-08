import type {
  CasePriority,
  CaseWorkflowState,
  IntakeFilters,
  OperationsCase,
  PaginatedResponse,
  QueueBucketCounts,
} from '@/contracts/operations'
import { categoryToOperationalStatus } from '@/lib/operationalStates'

export interface V1OpenCase {
  failure_id: string
  shipment_id: string
  category: string
  city?: string
  courier?: string
  text: string
}

function inferPriority(category: string): CasePriority {
  const c = category.toLowerCase()
  if (c.includes('escalation') || c.includes('critical')) return 'high'
  if (c.includes('hub') || c.includes('address')) return 'medium'
  return 'low'
}

export function v1CaseToOperations(c: V1OpenCase): OperationsCase {
  return {
    caseId: c.failure_id,
    shipmentId: c.shipment_id,
    issueSummary: c.text,
    city: c.city ?? null,
    courier: c.courier ?? null,
    category: c.category,
    priority: inferPriority(c.category),
    workflowState: 'OPEN',
    operationalStatus: categoryToOperationalStatus(c.category),
    runText: c.text,
  }
}

function matchesFilters(caseRow: OperationsCase, filters: IntakeFilters): boolean {
  if (filters.search) {
    const q = filters.search.toLowerCase()
    const hay = `${caseRow.shipmentId} ${caseRow.issueSummary} ${caseRow.city ?? ''} ${caseRow.category ?? ''}`.toLowerCase()
    if (!hay.includes(q)) return false
  }
  if (filters.priority !== 'all' && caseRow.priority !== filters.priority) return false
  if (filters.city !== 'all' && (caseRow.city ?? '') !== filters.city) return false
  if (filters.status !== 'all' && caseRow.workflowState !== filters.status) return false
  if (filters.cause !== 'all' && (caseRow.category ?? '') !== filters.cause) return false
  // V1 samples have no timestamps — time presets are no-ops until Dataset V2 provides opened_at.
  return true
}

export function paginateCases(
  cases: OperationsCase[],
  filters: IntakeFilters,
  limit: number,
  cursor: string | null,
): PaginatedResponse<OperationsCase> {
  const filtered = cases.filter((c) => matchesFilters(c, filters))
  const start = cursor ? Math.max(0, Number.parseInt(cursor, 10) || 0) : 0
  const slice = filtered.slice(start, start + limit)
  const next = start + limit < filtered.length ? String(start + limit) : null
  const prev = start > 0 ? String(Math.max(0, start - limit)) : null
  return { items: slice, total: filtered.length, nextCursor: next, prevCursor: prev }
}

export function queueCountsFromOpenCases(openCount: number): QueueBucketCounts {
  return {
    open: openCount,
    investigating: 0,
    needsReview: 0,
    awaitingApproval: 0,
    awaitingOutcome: 0,
    resolved: 0,
  }
}

export function activeWorkflowState(
  base: CaseWorkflowState,
  opts: {
    busy?: boolean
    hasRecommendation?: boolean
    hasReview?: boolean
    finalDisposition?: 'execute' | 'escalate' | null
  },
): CaseWorkflowState {
  if (opts.finalDisposition === 'escalate') return 'ESCALATED'
  if (opts.finalDisposition === 'execute') return 'AWAITING_OUTCOME'
  if (opts.busy) return 'INVESTIGATING'
  if (opts.hasReview) return 'AWAITING_APPROVAL'
  if (opts.hasRecommendation) return 'RECOMMENDATION_READY'
  return base
}
