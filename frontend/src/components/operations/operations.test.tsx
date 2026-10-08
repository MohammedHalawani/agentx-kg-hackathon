import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { paginateCases } from '@/adapters/v1SamplesAdapter'
import type { OperationsCase } from '@/contracts/operations'
import { CaseTransition } from './CaseTransition'
import { CursorPagination } from './Pagination'
import { workflowAllowsResolvedTransition } from '@/lib/operationalStates'

const sample: OperationsCase[] = Array.from({ length: 30 }, (_, i) => ({
  caseId: `f${i}`,
  shipmentId: `SHP-${String(i).padStart(4, '0')}`,
  issueSummary: `Issue ${i}`,
  priority: 'medium',
  workflowState: 'OPEN',
}))

describe('paginateCases', () => {
  it('returns cursor pages without rendering full list', () => {
    const filters = { search: '', timePreset: 'week' as const, priority: 'all' as const, city: 'all', status: 'all' as const, cause: 'all' }
    const page1 = paginateCases(sample, filters, 25, null)
    expect(page1.items).toHaveLength(25)
    expect(page1.total).toBe(30)
    expect(page1.nextCursor).toBe('25')
    const page2 = paginateCases(sample, filters, 25, '25')
    expect(page2.items).toHaveLength(5)
  })

  it('filters by search', () => {
    const filters = { search: 'SHP-0029', timePreset: 'week' as const, priority: 'all' as const, city: 'all', status: 'all' as const, cause: 'all' }
    const page = paginateCases(sample, filters, 25, null)
    expect(page.total).toBe(1)
  })
})

describe('CaseTransition semantics', () => {
  it('does not treat recommendation-ready as resolved path', () => {
    expect(workflowAllowsResolvedTransition('RECOMMENDATION_READY')).toBe(false)
    expect(workflowAllowsResolvedTransition('AWAITING_OUTCOME')).toBe(true)
  })

  it('highlights recommendation-ready state in the flow', () => {
    render(
      <LanguageProvider>
        <CaseTransition state="RECOMMENDATION_READY" />
      </LanguageProvider>,
    )
    expect(screen.getByText(/Recommendation ready/)).toBeTruthy()
  })
})

describe('CursorPagination RTL', () => {
  beforeEach(() => localStorage.setItem('agentx-language', 'ar'))
  afterEach(() => localStorage.removeItem('agentx-language'))

  it('renders Arabic pagination labels', () => {
    render(
      <LanguageProvider>
        <CursorPagination
          total={100}
          limit={25}
          cursorStart={0}
          nextCursor="25"
          prevCursor={null}
          onNext={() => undefined}
          onPrev={() => undefined}
          onLimitChange={() => undefined}
        />
      </LanguageProvider>,
    )
    expect(screen.getByText(/التالي/)).toBeTruthy()
  })
})
