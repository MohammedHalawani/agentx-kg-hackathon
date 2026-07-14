import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useFetch } from './useFetch'

afterEach(() => vi.unstubAllGlobals())

describe('useFetch refetch', () => {
  it('re-runs the GET and replaces data when refetch is called', async () => {
    let call = 0
    const fetchMock = vi.fn(() => {
      call += 1
      return Promise.resolve({ ok: true, json: async () => ({ n: call }) })
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useFetch<{ n: number }>('/graph'))
    await waitFor(() => expect(result.current.data?.n).toBe(1))

    act(() => result.current.refetch())
    await waitFor(() => expect(result.current.data?.n).toBe(2))

    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
