import { describe, expect, it, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useExploreData } from './useExploreData'
afterEach(() => vi.unstubAllGlobals())
describe('Explore operational source', () => {
  it('never turns endpoint failure into a fixture shipment', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
    const { result } = renderHook(() => useExploreData('needs_attention', 25))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data).toBeNull()
    expect(result.current.error).toContain('503')
    expect(result.current.isFixture).toBe(false)
  })
  it('preserves backend workflow and does not resolve delivered disputes', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ items: [{ shipment_id: 'DEMO-1', status: 'DELIVERED', operational_status: 'DELIVERY_DISPUTE', workflow_state: 'HUMAN_REVIEW', case_id: 'CASE-1' }], filtered_total: 1, next_cursor: null, previous_cursor: null }) }))
    const { result } = renderHook(() => useExploreData('needs_attention', 25))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.data?.shipments[0].needs_attention).toBe(true)
    expect(result.current.data?.shipments[0].workflow_state).toBe('HUMAN_REVIEW')
  })
  it('reports an incompatible endpoint contract instead of an empty map', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ shipments: [] }) }))
    const { result } = renderHook(() => useExploreData('all', 25))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.error).toBeTruthy()
    expect(result.current.data).toBeNull()
  })
})
