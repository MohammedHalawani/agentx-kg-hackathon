import { describe, expect, it } from 'vitest'
import { humanActionI18nKey, humanActionRequired } from './humanAction'

describe('humanAction', () => {
  it('maps workflow states to operator work labels', () => {
    expect(humanActionI18nKey('AWAITING_APPROVAL')).toBe('ops.actions.approve')
    expect(humanActionI18nKey('HUMAN_REVIEW')).toBe('ops.case.humanReview')
    expect(humanActionI18nKey('OPEN')).toBeNull()
  })

  it('flags states that need a human', () => {
    expect(humanActionRequired('AWAITING_OUTCOME')).toBe(true)
    expect(humanActionRequired('INVESTIGATING')).toBe(false)
  })
})
