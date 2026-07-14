import { afterEach, describe, expect, it, vi } from 'vitest'

// Fresh module per test so the module-level cache/inflight don't leak between cases.
async function freshLoad() {
  vi.resetModules()
  return (await import('./entityInfo')).loadLabels
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('entityInfo.loadLabels', () => {
  it('fetches label descriptions from /meta once and shares the result', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ labels: { Incident: 'x' } }) })
    vi.stubGlobal('fetch', fetchMock)
    const loadLabels = await freshLoad()
    expect(await loadLabels()).toEqual({ Incident: 'x' })
    expect(await loadLabels()).toEqual({ Incident: 'x' }) // served from cache
    expect(fetchMock).toHaveBeenCalledTimes(1) // shared fetch, not re-requested per caller
  })

  it('does NOT poison the cache on a failed fetch - a later call retries', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: false, status: 500 }) // first load fails
      .mockResolvedValue({ ok: true, json: async () => ({ labels: { Incident: 'x' } }) }) // retry succeeds
    vi.stubGlobal('fetch', fetchMock)
    const loadLabels = await freshLoad()
    expect(await loadLabels()).toEqual({}) // degrades gracefully, no throw
    expect(await loadLabels()).toEqual({ Incident: 'x' }) // retried instead of caching {} forever
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
