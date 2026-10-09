import type { LucideIcon } from 'lucide-react'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  HelpCircle,
  MapPinOff,
  PackageCheck,
  Scale,
  ShieldAlert,
  Timer,
  Truck,
  UserX,
} from 'lucide-react'
import type { CaseWorkflowState, OperationalShipmentStatus } from '@/contracts/operations'

export interface OperationalVisual {
  token: string
  Icon: LucideIcon
  labelKey: string
  hintKey?: string
  pattern?: 'solid' | 'dashed' | 'dot'
}

export function operationalLabelKey(status: string): string {
  return OPERATIONAL_STATUS_VISUAL[status as OperationalShipmentStatus]?.labelKey ?? status
}

export const OPERATIONAL_STATUS_VISUAL: Record<OperationalShipmentStatus, OperationalVisual> = {
  ON_TIME: { token: '--color-chart-good', Icon: PackageCheck, labelKey: 'ops.status.onTime', pattern: 'solid' },
  NEEDS_ATTENTION: { token: '--color-chart-warning', Icon: HelpCircle, labelKey: 'ops.status.needsAttention', hintKey: 'ops.statusHints.needsAttention', pattern: 'dashed' },
  SLA_RISK: { token: '--color-chart-warning', Icon: Timer, labelKey: 'ops.status.slaRisk', pattern: 'dashed' },
  CRITICAL: { token: '--color-danger', Icon: AlertTriangle, labelKey: 'ops.status.critical', pattern: 'solid' },
  UNRECONCILED_CUSTODY: { token: '--color-chart-orange', Icon: ShieldAlert, labelKey: 'ops.status.unreconciledCustody', pattern: 'dot' },
  DELIVERY_DISPUTE: { token: '--color-chart-orange', Icon: Scale, labelKey: 'ops.status.deliveryDispute', pattern: 'dot' },
  ADDRESS_CONFLICT: { token: '--color-chart-blue', Icon: MapPinOff, labelKey: 'ops.status.addressConflict', pattern: 'dashed' },
  RECIPIENT_UNAVAILABLE: { token: '--color-chart-warning', Icon: UserX, labelKey: 'ops.status.recipientUnavailable', pattern: 'dashed' },
  HUB_DELAY: { token: '--color-chart-warning', Icon: Truck, labelKey: 'ops.status.hubDelay', pattern: 'dashed' },
  RESOLVED: { token: '--color-chart-good', Icon: CheckCircle2, labelKey: 'ops.status.resolved', pattern: 'solid' },
}

export const CASE_WORKFLOW_VISUAL: Record<CaseWorkflowState, OperationalVisual> = {
  OPEN: { token: '--color-chart-blue', Icon: HelpCircle, labelKey: 'ops.case.open' },
  INVESTIGATING: { token: '--color-chart-blue', Icon: Clock3, labelKey: 'ops.case.investigating' },
  NEEDS_EVIDENCE: { token: '--color-chart-warning', Icon: HelpCircle, labelKey: 'ops.case.needsEvidence' },
  RECOMMENDATION_READY: { token: '--color-chart-aqua', Icon: PackageCheck, labelKey: 'ops.case.recommendationReady' },
  AWAITING_APPROVAL: { token: '--color-chart-warning', Icon: Scale, labelKey: 'ops.case.awaitingApproval', hintKey: 'ops.caseHints.awaitingApproval' },
  ACTION_INITIATED: { token: '--color-chart-blue', Icon: Truck, labelKey: 'ops.case.actionInitiated' },
  REJECTED: { token: '--color-chart-warning', Icon: Scale, labelKey: 'ops.case.rejected' },
  HUMAN_REVIEW: { token: '--color-chart-orange', Icon: UserX, labelKey: 'ops.case.humanReview', hintKey: 'ops.caseHints.humanReview' },
  AWAITING_OUTCOME: { token: '--color-chart-warning', Icon: Timer, labelKey: 'ops.case.awaitingOutcome', hintKey: 'ops.caseHints.awaitingOutcome' },
  ESCALATED: { token: '--color-danger', Icon: AlertTriangle, labelKey: 'ops.case.escalated' },
  REOPENED: { token: '--color-chart-blue', Icon: HelpCircle, labelKey: 'ops.case.reopened' },
  RESOLVED: { token: '--color-chart-good', Icon: CheckCircle2, labelKey: 'ops.case.resolved', hintKey: 'ops.caseHints.resolved' },
}

/** Recommendation / review completion must not imply RESOLVED — only verified outcomes may. */
export function workflowAllowsResolvedTransition(from: CaseWorkflowState): boolean {
  return from === 'AWAITING_OUTCOME' || from === 'REOPENED'
}

export function categoryToOperationalStatus(category?: string | null): OperationalShipmentStatus | null {
  if (!category) return null
  const c = category.toLowerCase().replace(/_/g, ' ')
  if (c.includes('address')) return 'ADDRESS_CONFLICT'
  if (c.includes('recipient')) return 'RECIPIENT_UNAVAILABLE'
  if (c.includes('hub')) return 'HUB_DELAY'
  if (c.includes('custody')) return 'UNRECONCILED_CUSTODY'
  if (c.includes('dispute')) return 'DELIVERY_DISPUTE'
  if (c.includes('escalation')) return 'CRITICAL'
  return 'SLA_RISK'
}
