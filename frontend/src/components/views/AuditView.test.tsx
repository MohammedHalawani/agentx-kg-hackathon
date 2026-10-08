import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { AuditView } from './AuditView'

const state = vi.hoisted(() => ({ error: null as string | null, request: vi.fn(), retry: vi.fn() }))
vi.mock('@/hooks/useFetch', () => ({ useFetch: (url: string) => { state.request(url); return { loading: false, error: state.error, refetch: state.retry, data: state.error ? null : { items: [{ id: 'actual-ledger-1', timestamp: '2026-10-08T08:00:00Z', shipment_id: 'DEMO-SHIP-1', case_id: 'CASE-1', event_type: 'OUTCOME_OBSERVED', actor: 'operator' }], filtered_total: 26, next_cursor: 'opaque-cursor', previous_cursor: null, metadata: { filter_choices: { event_type: ['OUTCOME_OBSERVED'] } } } } } }))
beforeEach(() => { state.error = null; vi.clearAllMocks(); localStorage.clear() })
describe('Audit operational ledger', () => {
  it('uses server data and opaque cursors without rendering fixtures', () => {
    render(<LanguageProvider><AuditView /></LanguageProvider>)
    expect(screen.getByText('DEMO-SHIP-1')).toBeTruthy()
    expect(screen.queryByText('SHP-0142')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(state.request.mock.lastCall?.[0]).toContain('cursor=opaque-cursor')
  })
  it('shows failures explicitly with retry', () => {
    state.error = 'Request failed (503)'
    render(<LanguageProvider><AuditView /></LanguageProvider>)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.queryByText('DEMO-SHIP-1')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(state.retry).toHaveBeenCalled()
  })
})
