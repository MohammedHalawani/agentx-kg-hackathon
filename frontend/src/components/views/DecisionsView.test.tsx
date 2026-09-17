import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { DecisionsView } from './DecisionsView'
import type { CasesOverview } from '../../types/agent'

const mockFetch = vi.hoisted(() => ({
  data: {
    coverage: { resolved: 8, unresolved: 2, total: 10 },
    writebacks: { by_agent: 3, seeded: 5, pending: 2, total: 10 },
    escalations: [],
    escalations_by_team: [],
    by_category: [
      {
        category: 'failed_attempt_barcode_mismatch',
        cases: 7,
        succeeded: 7,
        success_rate: 100,
      },
      {
        category: 'address_conflict',
        cases: 10,
        succeeded: 8,
        success_rate: 80,
      },
      {
        category: 'escalation:weight_mismatch',
        cases: 5,
        succeeded: 5,
        success_rate: 100,
      },
    ],
    by_action: [
      { action: 'Reschedule delivery', used: 5, succeeded: 5, success_rate: 100 },
      { action: 'Contact courier', used: 10, succeeded: 6, success_rate: 60 },
    ],
    queue: Array.from({ length: 12 }, (_, i) => ({
      failure_id: `f-${i}`,
      shipment_id: `SHP-${i}`,
      category: 'failed_attempt_barcode_mismatch',
      city: 'Riyadh',
      courier: 'Courier A',
    })),
  } as CasesOverview,
  loading: false,
}))

vi.mock('../../hooks/useFetch', () => ({
  useFetch: () => mockFetch,
}))

function renderDecisions() {
  return render(
    <ThemeProvider>
      <LanguageProvider>
        <DecisionsView />
      </LanguageProvider>
    </ThemeProvider>,
  )
}

beforeEach(() => {
  mockFetch.loading = false
})

describe('DecisionsView panel heights (L01)', () => {
  it('preserves 440px trio and 400px queue height constants', () => {
    renderDecisions()

    const panelCards = Array.from(document.querySelectorAll('.h-\\[440px\\]'))
    expect(panelCards.length).toBeGreaterThanOrEqual(3)

    const queueCard = document.querySelector('.h-\\[400px\\]')
    expect(queueCard).not.toBeNull()
  })
})

describe('DecisionsView metric semantics (M01–M05, D01)', () => {
  it('uses segmented outcome bars instead of single primary fill', () => {
    renderDecisions()

    const segments = document.querySelectorAll('[data-slot="segmented-progress-segment"]')
    expect(segments.length).toBeGreaterThan(0)

    const primaryIndicators = document.querySelectorAll('[data-slot="progress-indicator"].bg-primary')
    expect(primaryIndicators.length).toBe(0)

    expect(document.querySelector('[data-variant="success"]')).not.toBeNull()
    expect(document.querySelector('[data-variant="failure"]')).not.toBeNull()
    expect(document.querySelector('[data-variant="pending"]')).not.toBeNull()
  })

  it('renders full-green bar for 100% success and red segment for partial success', () => {
    renderDecisions()

    const metricButtons = screen.getAllByRole('button')
    const fullSuccess = metricButtons.find((btn) => btn.textContent?.includes('100%'))
    const partialSuccess = metricButtons.find((btn) => btn.textContent?.includes('80%'))

    expect(fullSuccess).toBeTruthy()
    expect(partialSuccess).toBeTruthy()

    const fullSegments = fullSuccess!.querySelectorAll('[data-variant]')
    const partialSegments = partialSuccess!.querySelectorAll('[data-variant]')

    expect(fullSegments.length).toBe(1)
    expect(fullSegments[0]?.getAttribute('data-variant')).toBe('success')
    expect(partialSegments.length).toBe(2)
  })

  it('splits coverage bar into resolved (success) and open (pending) segments', () => {
    renderDecisions()

    const coverageCard = screen.getByText('Case coverage').closest('[data-slot="card"]')
    expect(coverageCard).toBeTruthy()

    const coverageSegments = coverageCard!.querySelectorAll('[data-variant="success"], [data-variant="pending"]')
    expect(coverageSegments.length).toBe(2)
  })

  it('uses neutral styling for learning badge when agent writebacks exist', () => {
    renderDecisions()

    const badge = screen.getByText(/3 agent precedent/)
    expect(badge.className).not.toContain('text-chart-good')
    expect(badge.className).toContain('text-muted-foreground')
  })

  it('surfaces pending writebacks when present (D01)', () => {
    renderDecisions()

    expect(screen.getAllByText(/2 pending/).length).toBeGreaterThanOrEqual(1)
  })

  it('computes overall historical rate including escalation categories', () => {
    renderDecisions()

    // (7+8+5) succeeded / (7+10+5) cases = 20/22 ≈ 91%
    expect(screen.getByText('91%')).toBeTruthy()
  })
})

describe('DecisionsView sticky scroll structure (L02, L03)', () => {
  it('uses overflow-auto scroll owner for queue instead of ScrollArea', () => {
    renderDecisions()

    const queueTitle = screen.getByText(/Open case queue/)
    const queueCard = queueTitle.closest('.h-\\[400px\\]')
    expect(queueCard).toBeTruthy()

    const scrollOwner = queueCard!.querySelector('.overflow-auto')
    expect(scrollOwner).toBeTruthy()
    expect(queueCard!.querySelector('[data-slot="scroll-area"]')).toBeNull()
  })

  it('declares sticky header on queue and focus matching-cases tables', () => {
    renderDecisions()

    const stickyHeaders = document.querySelectorAll('thead.sticky')
    expect(stickyHeaders.length).toBeGreaterThanOrEqual(2)
  })
})

describe('DecisionsView pending strings (I04)', () => {
  beforeEach(() => {
    localStorage.setItem('agentx-language', 'ar')
  })

  afterEach(() => {
    localStorage.removeItem('agentx-language')
  })

  it('shows Arabic pending fragment when writebacks are pending', () => {
    renderDecisions()
    expect(document.querySelector('.text-outcome-pending')?.textContent).toContain('2 معلّق')
    expect(screen.queryByText(/2 pending/)).toBeNull()
  })
})
