import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { SimulationView } from './SimulationView'

const command = vi.hoisted(() => vi.fn())
const reset = vi.hoisted(() => ({ value: { enabled: false, confirmation: null as string | null } }))
vi.mock('@/hooks/useQueueSimulation', () => ({
  useOperationsControl: () => ({
    data: { synthetic: true, as_of: '2026-09-02T08:00:00Z', session: { case_source: 'monitor', monitor_checked: 3, monitor_opened: 1 },
            simulator: { state: 'paused', speed: 1, event_count: 12, replay_mode: 'timeline' }, development_reset: reset.value },
    loading: false, error: null, pending: false, refetch: vi.fn(), command,
  }),
}))

describe('Development simulation view', () => {
  it('holds the world clock and session controls, labelled as development tooling', () => {
    render(<LanguageProvider><SimulationView /></LanguageProvider>)
    expect(screen.getByRole('button', { name: 'Start world' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /New live session/ })).toBeTruthy()
    expect(screen.getByText('Synthetic simulation')).toBeTruthy()
    expect(screen.getAllByText(/Synthetic operational data/i).length).toBeGreaterThan(0)
  })
  it('offers no ledger reset unless the server enables it, and sends the session confirmation', async () => {
    reset.value = { enabled: false, confirmation: null }
    const { unmount } = render(<LanguageProvider><SimulationView /></LanguageProvider>)
    expect(screen.getByRole('button', { name: /New live session/ }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByTestId('reset-disabled').textContent).toContain('SUHAIL_DEV_RESET=1')
    unmount()
    reset.value = { enabled: true, confirmation: 'RESET-LEDGER-0123456789abcdef01234567' }
    render(<LanguageProvider><SimulationView /></LanguageProvider>)
    fireEvent.click(screen.getByRole('button', { name: /New live session/ }))
    expect(screen.getByText(/RESET-LEDGER-0123456789abcdef01234567/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Start new session' }))
    await waitFor(() => expect(command).toHaveBeenCalledWith('reset', { confirmation: 'RESET-LEDGER-0123456789abcdef01234567' }))
  })
})
