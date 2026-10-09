import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { SimulationView } from './SimulationView'

const command = vi.hoisted(() => vi.fn())
vi.mock('@/hooks/useQueueSimulation', () => ({
  useOperationsControl: () => ({
    data: { synthetic: true, as_of: '2026-09-02T08:00:00Z', session: { case_source: 'monitor', monitor_checked: 3, monitor_opened: 1 },
            simulator: { state: 'paused', speed: 1, event_count: 12, replay_mode: 'timeline' } },
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
})
