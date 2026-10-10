import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { adaptCase, type ApiCase } from '@/adapters/operationsApi'
import { CaseSummaryText } from './CaseSummaryText'
import { CaseCard } from './CaseCard'

// A rules-only case as an older ledger may still hold it: rule triage text and a rule category.
const ruleRow: ApiCase = { case_id: 'SYN-CASE-1', shipment_id: 'SYN-SHP-1', issue_summary: 'Observed gate differs from instruction effective at attempt', category: 'WRONG_GATE', symptom_codes: ['DELIVERY_ATTEMPT_FAILED', 'MILESTONE_OVERDUE'], priority: 'medium', workflow_state: 'AWAITING_APPROVAL', diagnosis_available: false, summary_source: 'monitor', rule_signal_codes: ['WRONG_GATE'] }

describe('Queue rows never present rule triage as the case', () => {
  it('drops a category the backend did not derive from an accepted diagnosis', () => {
    expect(adaptCase(ruleRow).category).toBeNull()
    expect(adaptCase(ruleRow).diagnosisAvailable).toBe(false)
    const { diagnosis_available: _flag, summary_source: _source, ...unflagged } = ruleRow
    expect(adaptCase(unflagged).category).toBeNull()  // A row without the flag is not a diagnosis either.
    expect(adaptCase({ ...ruleRow, diagnosis_available: true, summary_source: 'agent_diagnosis', category: 'DELAYED_SYNC' }).category).toBe('DELAYED_SYNC')
  })

  it('shows what the monitor observed, never the rule text, when there is no accepted diagnosis', () => {
    render(<LanguageProvider><CaseSummaryText row={adaptCase(ruleRow)} /></LanguageProvider>)
    expect(screen.getByText('Observed: Delivery attempt failed · Expected milestone overdue · no accepted diagnosis')).toBeTruthy()
    expect(document.body.textContent).not.toContain('Observed gate differs')
    expect(document.body.textContent).not.toMatch(/Wrong gate/)
  })

  it('labels an accepted diagnosis as the agent’s', () => {
    const row = adaptCase({ ...ruleRow, diagnosis_available: true, summary_source: 'agent_diagnosis', category: 'DELAYED_SYNC', issue_summary: 'Buffered scans explain the gap.' })
    render(<LanguageProvider><CaseSummaryText row={row} /></LanguageProvider>)
    expect(document.querySelector('[data-summary-source="agent_diagnosis"]')!.textContent).toBe('Agent diagnosis: Buffered scans explain the gap.')
  })

  it('never names a rule category on a case card', () => {
    render(<LanguageProvider><CaseCard caseRow={{ ...adaptCase(ruleRow), category: 'WRONG_GATE', operationalStatus: null }} onSelect={() => {}} /></LanguageProvider>)
    expect(document.body.textContent).not.toMatch(/Wrong gate/)
    expect(screen.getByText('No accepted diagnosis yet')).toBeTruthy()
    expect(screen.getByText('Delivery attempt failed · Expected milestone overdue')).toBeTruthy()
  })
})
