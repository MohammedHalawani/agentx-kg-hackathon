import { describe, expect, it } from 'vitest'
import type { ShipmentDetail } from '@/contracts/caseDetail'
import { en } from '@/i18n/en'
import { ar } from '@/i18n/ar'
import { humanReviewReasonKey } from './humanReviewReason'

// V3.4.2: a case routed to a person because the investigation reached its context limit (AUTH-28) gets its own reason.
describe('humanReviewReasonKey', () => {
  it('names the context limit for AUTH-28 in both languages', () => {
    const detail = {
      workflow_state: 'HUMAN_REVIEW', outcome: null, executions: [],
      review: { verdict: 'no_proposal', reason_code: 'INVESTIGATOR_CONTEXT_EXHAUSTED' },
      run: { result: { authority: { rule_id: 'AUTH-28-context-exhausted' } } },
    } as unknown as ShipmentDetail
    expect(humanReviewReasonKey(detail)).toBe('ops.overview.humanReason.contextExhausted')
    expect(en.ops.overview.humanReason.contextExhausted).toMatch(/context limit/)
    expect(en.ops.overview.humanReason.contextExhausted).toMatch(/preserved for human review/)
    expect(ar.ops.overview.humanReason.contextExhausted).toMatch(/حد السياق/)
  })
})
