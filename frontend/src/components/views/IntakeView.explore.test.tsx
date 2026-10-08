import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { IntakeView } from './IntakeView'
import type { ExploreShipment } from '../../types/explore'

const { run } = vi.hoisted(() => ({ run: vi.fn() }))
vi.mock('../../hooks/useComplaintStream', () => ({ useComplaintStream: () => ({ stages: [], final: null, caseFile: null, busy: false, error: null, complaint: '', run, stop: vi.fn(), reset: vi.fn() }) }))
vi.mock('../artifacts/Graph', () => ({ Graph: () => <div>Shipment evidence graph</div> }))

const shipment: ExploreShipment = { shipment_id: 'SHP-0004', status: 'FAILED', priority: 'high', root_causes: ['hub_delay'], needs_attention: true, critical: true, stalled: true, delivered: false, last_event: null, origin: null, destinations: [] }
function setup(cases: unknown[]) {
  localStorage.setItem('agentx-language', 'en')
  vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url === '/samples' ? { cases } : { nodes: [{ id: 'n1', labels: ['Shipment'], caption: 'SHP-0004', properties: {} }], relationships: [] } })))
  render(<LanguageProvider><IntakeView selectedShipment={shipment} /></LanguageProvider>)
}
afterEach(() => { run.mockReset(); vi.unstubAllGlobals(); localStorage.clear() })

describe('Explore → Intake inspection', () => {
  it('does not run the agent on navigation; an unresolved case runs only with its canonical complaint', async () => {
    setup([{ failure_id: 'FAIL-4', shipment_id: 'SHP-0004', category: 'hub_delay', text: 'Canonical symptom complaint' }])
    await screen.findByRole('button', { name: 'Analyze shipment' })
    expect(run).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze shipment' }))
    expect(run).toHaveBeenCalledExactlyOnceWith('Canonical symptom complaint')
  })

  it('keeps pending or historical cases evidence-only without an unresolved worklist entry', async () => {
    setup([])
    await screen.findByText('Shipment evidence graph')
    await waitFor(() => expect(screen.queryByText('Loading…')).toBeNull())
    expect(screen.queryByRole('button', { name: 'Analyze shipment' })).toBeNull()
    expect(screen.getByText(/Evidence only: no matching unresolved failure/)).toBeTruthy()
    expect(run).not.toHaveBeenCalled()
  })
})
