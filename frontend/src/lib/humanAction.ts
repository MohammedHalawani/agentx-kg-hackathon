import type { CaseWorkflowState } from '@/contracts/operations'

/** i18n key (full path) for pending operator work — distinct from operational NEEDS ATTENTION. */
export function humanActionI18nKey(state: CaseWorkflowState): string | null {
  switch (state) {
    case 'AWAITING_APPROVAL':
      return 'ops.actions.approve'
    case 'HUMAN_REVIEW':
      return 'ops.case.humanReview'
    case 'AWAITING_OUTCOME':
      return 'ops.actions.observe'
    case 'NEEDS_EVIDENCE':
      return 'ops.actions.request_evidence'
    case 'REJECTED':
      return 'ops.actions.reanalyze'
    default:
      return null
  }
}

export function humanActionRequired(state: CaseWorkflowState): boolean {
  return humanActionI18nKey(state) != null
}
