import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { ExploreView } from './ExploreView'
import type { ExploreData, ExploreShipment } from '../../types/explore'

vi.mock('../artifacts/Graph', () => ({ Graph: ({ graph, onNodeSelect }: { graph: ExploreData['graph']; onNodeSelect: (node: ExploreData['graph']['nodes'][number]) => void }) => <button onClick={() => onNodeSelect?.(graph.nodes[0])}>Graph shipment {graph.nodes[0]?.caption}</button> }))
vi.mock('./ExploreMap', () => ({ ExploreMap: ({ shipments, onSelect }: { shipments: ExploreShipment[]; onSelect: (s: ExploreShipment) => void }) => <button onClick={() => onSelect(shipments[0])}>Map shipment {shipments[0].shipment_id}</button> }))
vi.mock('./SchemaView', () => ({ SchemaView: () => <div>Schema</div> }))

const shipment: ExploreShipment = { shipment_id: 'SHP-0004', status: 'FAILED', priority: 'high', root_causes: ['hub_delay'], needs_attention: true, critical: true, stalled: true, delivered: false, last_event: { event_type: 'HUB_DELAY', timestamp: '2026-01-01' }, origin: null, destinations: [], city: 'Riyadh' }
const apiPage = { items: [{ ...shipment, cause_codes: shipment.root_causes, operational_status: 'HUB_DELAY', case_id: 'CASE-4', workflow_state: 'OPEN' }], filtered_total: 70, next_cursor: null, previous_cursor: null }
const detail = { shipment_id: shipment.shipment_id, evidence: { nodes: [{ id: 'n1', kind: 'Shipment', properties: { shipment_id: shipment.shipment_id } }], edges: [] } }

beforeEach(() => localStorage.setItem('agentx-language', 'en'))
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
function setup() { const onOpenCase = vi.fn(); render(<LanguageProvider><ExploreView onOpenCase={onOpenCase} /></LanguageProvider>); return onOpenCase }

describe('operational Explore', () => {
  it('shares the default/filter/selection between map and graph and opens the case explicitly', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url.startsWith('/shipments/') ? detail : apiPage }))
    vi.stubGlobal('fetch', fetchMock)
    const onOpenCase = setup()
    await screen.findByRole('button', { name: 'Map shipment SHP-0004' })
    expect(fetchMock.mock.calls[0][0]).toBe('/explore?filter=needs_attention&limit=25')
    fireEvent.click(screen.getByRole('button', { name: 'Map shipment SHP-0004' }))
    expect(onOpenCase).not.toHaveBeenCalled()
    expect(screen.getByText('High (derived)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Graph' }))
    await screen.findByRole('button', { name: 'Graph shipment SHP-0004' })
    expect(fetchMock.mock.calls.some(([url]) => url === '/shipments/SHP-0004/context')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Open case in Intake' }))
    expect(onOpenCase).toHaveBeenCalledWith(expect.objectContaining({ shipment_id: shipment.shipment_id, case_id: 'CASE-4' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delivered', exact: true }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/explore?filter=delivered&limit=25')).toBe(true))
    expect(screen.queryByRole('button', { name: 'Open case in Intake' })).toBeNull()
    expect(screen.queryByText(/lost|unaccounted/i)).toBeNull()
  })

  it('displays loading, transport error and a retry that reaches a genuine empty result', async () => {
    let fail: (error: Error) => void = () => {}
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject })).mockResolvedValueOnce({ ok: true, json: async () => ({ ...apiPage, items: [], filtered_total: 0 }) })
    vi.stubGlobal('fetch', fetchMock)
    setup()
    expect(screen.getByRole('status').textContent).toContain('Loading shipment evidence')
    await act(async () => fail(new Error('network')))
    expect(screen.getByRole('alert').textContent).toContain('could not be loaded')
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByText('No shipments match this filter.')
  })

  it('preserves Arabic UI and Latin shipment identifiers', async () => {
    localStorage.setItem('agentx-language', 'ar')
    vi.stubGlobal('fetch', vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url.startsWith('/shipments/') ? detail : apiPage })))
    setup()
    await screen.findByRole('button', { name: 'Map shipment SHP-0004' })
    expect(screen.getByRole('button', { name: 'تحتاج انتباهًا', exact: true }).getAttribute('aria-pressed')).toBe('true')
    const id = screen.getByText('SHP-0004')
    expect(id.getAttribute('dir')).toBe('ltr')
    fireEvent.click(screen.getByRole('button', { name: 'Map shipment SHP-0004' }))
    expect(screen.getByText('تأخر في مركز المعالجة')).toBeTruthy()
    expect(screen.getByRole('region', { name: 'تفاصيل الشحنة المحددة' }).getAttribute('dir')).toBe('rtl')
  })
})
