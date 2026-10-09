import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { IntakeView } from './IntakeView'
import type { ExploreShipment } from '../../types/explore'
const { post } = vi.hoisted(() => ({ post: vi.fn() }))
vi.mock('@/lib/operationsClient', () => ({ operationsPost: post }))
vi.mock('../artifacts/Graph', () => ({ Graph: () => <div>Shipment evidence graph</div> }))
vi.mock('@/components/operations/ShipmentRouteMap', () => ({ ShipmentRouteMap: () => <div>Shipment route evidence</div> }))
const shipment: ExploreShipment = { shipment_id: 'SHP-0004', status: 'IN_TRANSIT', priority: 'high', root_causes: ['HUB_DELAY'], needs_attention: true, critical: false, stalled: true, delivered: false, last_event: null, origin: null, destinations: [] }
function setup(active: boolean) {
  localStorage.setItem('agentx-language', 'en')
  const detail = { shipment_id: shipment.shipment_id, case_id: active ? 'CASE-4' : undefined, workflow_state: active ? 'OPEN' : undefined, state_version: 1, evidence: { nodes: [], edges: [] } }
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url.startsWith('/cases/queue') ? { items: [], filtered_total: 0 } : url.endsWith('/status') ? {} : detail }))
  vi.stubGlobal('fetch', fetchMock)
  post.mockResolvedValue({})
  render(<LanguageProvider><IntakeView selectedShipment={{ ...shipment, case_id: active ? 'CASE-4' : undefined }} /></LanguageProvider>)
  return fetchMock
}
afterEach(() => { post.mockReset(); vi.unstubAllGlobals(); localStorage.clear() })
describe('Explore → V2 Intake inspection', () => {
  it('reads a canonical queued case without requiring operator pipeline steps', async () => {
    const fetchMock = setup(true)
    await screen.findByText(/Queued for automatic sequential triage/)
    expect(post).not.toHaveBeenCalled()
    expect(fetchMock.mock.calls.some(([url]) => url === '/cases/CASE-4')).toBe(true)
    expect(fetchMock.mock.calls.some(([url]) => url.startsWith('/v1/') || url === '/samples')).toBe(false)
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Approve action' })).toBeNull()
  })
  it('keeps a shipment without an active case evidence-only', async () => {
    const fetchMock = setup(false)
    await screen.findByText(/Evidence only/)
    expect(fetchMock.mock.calls.some(([url]) => url === '/shipments/SHP-0004/context')).toBe(true)
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    expect(post).not.toHaveBeenCalled()
  })
})
