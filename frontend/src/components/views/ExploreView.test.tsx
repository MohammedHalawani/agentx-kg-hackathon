import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { ExploreView } from './ExploreView'
import type { ExploreData, ExploreShipment } from '../../types/explore'

vi.mock('../artifacts/Graph', () => ({ Graph: ({ graph, onNodeSelect }: { graph: ExploreData['graph']; onNodeSelect: (node: ExploreData['graph']['nodes'][number]) => void }) => <button onClick={() => onNodeSelect?.(graph.nodes[0])}>Graph shipment {graph.nodes[0]?.caption}</button> }))
vi.mock('./ExploreMap', () => ({ ExploreMap: ({ shipments, onSelect }: { shipments: ExploreShipment[]; onSelect: (s: ExploreShipment) => void }) => <button onClick={() => onSelect(shipments[0])}>Map shipment {shipments[0].shipment_id}</button> }))
vi.mock('./SchemaView', () => ({ SchemaView: () => <div>Schema</div> }))

const shipment: ExploreShipment = { shipment_id: 'SHP-0004', status: 'FAILED', priority: 'high', root_causes: ['hub_delay'], needs_attention: true, critical: true, stalled: true, delivered: false, last_event: { event_type: 'HUB_DELAY', timestamp: '2026-01-01' }, origin: null, destinations: [], city: 'Riyadh' }
const data: ExploreData = { shipments: [shipment], counts: { all: 300, needs_attention: 70, critical: 28, stalled: 16, delivered: 80 }, filter: 'needs_attention', limit: 25, returned: 1, total: 70, truncated: true, graph: { nodes: [{ id: 'n1', labels: ['Shipment'], caption: shipment.shipment_id, properties: { shipment_id: shipment.shipment_id } }], relationships: [] } }

beforeEach(() => localStorage.setItem('agentx-language', 'en'))
afterEach(() => { vi.unstubAllGlobals(); localStorage.clear() })
function setup() { const onOpenCase = vi.fn(); render(<LanguageProvider><ExploreView onOpenCase={onOpenCase} /></LanguageProvider>); return onOpenCase }

describe('operational Explore', () => {
  it('shares the default/filter/selection between map and graph and opens the case explicitly', async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve({ ok: true, json: async () => url.startsWith('/graph?') ? data.graph : data }))
    vi.stubGlobal('fetch', fetchMock)
    const onOpenCase = setup()
    await screen.findByRole('button', { name: 'Map shipment SHP-0004' })
    expect(fetchMock.mock.calls[0][0]).toBe('/explore?filter=needs_attention&limit=25')
    fireEvent.click(screen.getByRole('button', { name: 'Map shipment SHP-0004' }))
    expect(onOpenCase).not.toHaveBeenCalled()
    expect(screen.getByText('High (derived)')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Graph' }))
    await screen.findByRole('button', { name: 'Graph shipment SHP-0004' })
    expect(fetchMock.mock.calls.some(([url]) => url === '/graph?shipment_id=SHP-0004')).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Open case in Intake' }))
    expect(onOpenCase).toHaveBeenCalledWith(shipment)
    fireEvent.click(screen.getByRole('button', { name: /Delivered \(80\)/ }))
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => url === '/explore?filter=delivered&limit=25')).toBe(true))
    expect(screen.queryByRole('button', { name: 'Open case in Intake' })).toBeNull()
    expect(screen.queryByText(/lost|unaccounted/i)).toBeNull()
  })

  it('displays loading, transport error and a retry that reaches a genuine empty result', async () => {
    let fail: (error: Error) => void = () => {}
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise((_resolve, reject) => { fail = reject })).mockResolvedValueOnce({ ok: true, json: async () => ({ ...data, shipments: [] }) })
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
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => data }))
    setup()
    await screen.findByRole('button', { name: 'Map shipment SHP-0004' })
    expect(screen.getByRole('button', { name: /تحتاج متابعة \(70\)/ }).getAttribute('aria-pressed')).toBe('true')
    const id = screen.getByText('SHP-0004')
    expect(id.getAttribute('dir')).toBe('ltr')
    fireEvent.click(screen.getByRole('button', { name: 'Map shipment SHP-0004' }))
    expect(screen.getByText('تأخر في مركز المعالجة')).toBeTruthy()
    expect(screen.getByRole('region', { name: 'تفاصيل الشحنة المحددة' }).getAttribute('dir')).toBe('rtl')
  })
})
