import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useChatStream } from './useChatStream'
import { streamChat } from '../lib/sse'

// streamChat is the network boundary; mock it so we drive the handlers/abort ourselves.
vi.mock('../lib/sse', () => ({ streamChat: vi.fn() }))

// loadThread hits /threads/{id}; tests that touch it stub fetch before rendering the hook.
const stubFetch = (messages: unknown[] = []) =>
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages }) }))

afterEach(() => {
  vi.unstubAllGlobals()
  ;(streamChat as Mock).mockReset()
})

describe('useChatStream thread id', () => {
  it('starts every visit fresh: new thread id, empty messages, NO restore fetch', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useChatStream())
    expect(result.current.threadId).toBeTruthy()
    expect(result.current.messages).toEqual([])
    await act(async () => {})
    expect(fetchMock).not.toHaveBeenCalled() // a previous conversation is never auto-restored
  })

  it('two visits get different thread ids (no cross-visit default)', () => {
    stubFetch()
    const a = renderHook(() => useChatStream())
    const b = renderHook(() => useChatStream())
    expect(a.result.current.threadId).not.toBe(b.result.current.threadId)
  })
})

describe('useChatStream send', () => {
  it('appends user + assistant messages, streams tokens, and clears busy on done', async () => {
    stubFetch()
    let handlers: Record<string, (arg?: unknown) => void> = {}
    let threadIdSeen: string | undefined
    let resolveStream: () => void = () => {}
    ;(streamChat as Mock).mockImplementation((_q, _h, h, _sig, tid) => {
      handlers = h
      threadIdSeen = tid
      return new Promise<void>((res) => {
        resolveStream = res
      })
    })

    const { result } = renderHook(() => useChatStream())
    await act(async () => {})

    act(() => result.current.send('How many incidents?'))
    expect(result.current.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
    expect(result.current.messages[0].content).toBe('How many incidents?')
    expect(result.current.busy).toBe(true)
    expect(threadIdSeen).toBe(result.current.threadId) // the active thread id rides along

    act(() => {
      handlers.onText('There are ')
      handlers.onText('37.')
    })
    expect(result.current.messages[1].content).toBe('There are 37.')

    act(() => handlers.onDone())
    await act(async () => resolveStream())
    await waitFor(() => expect(result.current.busy).toBe(false))
    expect(result.current.messages[1].streaming).toBe(false)
  })

  it('does not send while busy or on empty input', async () => {
    stubFetch()
    ;(streamChat as Mock).mockReturnValue(new Promise<void>(() => {})) // never resolves -> stays busy
    const { result } = renderHook(() => useChatStream())
    await act(async () => {})
    act(() => result.current.send('   ')) // whitespace only
    expect(result.current.messages).toEqual([])
    act(() => result.current.send('first'))
    act(() => result.current.send('second')) // ignored: busy
    expect(result.current.messages.map((m) => m.content)).toEqual(['first', ''])
  })
})

describe('useChatStream stop + errors', () => {
  it('stop aborts the in-flight signal and records no error', async () => {
    stubFetch()
    let signal: AbortSignal | undefined
    ;(streamChat as Mock).mockImplementation((_q, _h, _handlers, sig) => {
      signal = sig
      return new Promise<void>((_res, rej) => {
        sig?.addEventListener('abort', () => rej(new DOMException('aborted', 'AbortError')))
      })
    })

    const { result } = renderHook(() => useChatStream())
    await act(async () => {})
    act(() => result.current.send('q'))
    expect(signal?.aborted).toBe(false)

    await act(async () => result.current.stop())
    expect(signal?.aborted).toBe(true)
    await waitFor(() => expect(result.current.busy).toBe(false))
    expect(result.current.messages[1].error).toBeFalsy() // an abort is a user action, not an error
  })

  it('flags the assistant message on a non-abort failure', async () => {
    stubFetch()
    ;(streamChat as Mock).mockRejectedValue(new Error('network'))
    const { result } = renderHook(() => useChatStream())
    await act(async () => {})
    await act(async () => result.current.send('q'))
    await waitFor(() => expect(result.current.messages[1]?.error).toBe(true))
    expect(result.current.busy).toBe(false)
  })
})

describe('useChatStream thread switching', () => {
  it('newThread clears messages and mints a fresh id', async () => {
    stubFetch()
    ;(streamChat as Mock).mockResolvedValue(undefined)
    const { result } = renderHook(() => useChatStream())
    await act(async () => {})
    const first = result.current.threadId
    await act(async () => result.current.send('q'))
    expect(result.current.messages.length).toBeGreaterThan(0)

    act(() => result.current.newThread())
    expect(result.current.messages).toEqual([])
    expect(result.current.threadId).not.toBe(first)
  })

  it('loadThread fetches a past thread and replaces the messages', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [
            { role: 'user', content: 'old q' },
            { role: 'assistant', content: 'old a' },
          ],
        }),
      }),
    )
    const { result } = renderHook(() => useChatStream())
    await act(async () => {})
    await act(async () => result.current.loadThread('past-1'))
    expect(fetch).toHaveBeenCalledWith('/threads/past-1')
    expect(result.current.messages.map((m) => m.content)).toEqual(['old q', 'old a'])
    expect(result.current.threadId).toBe('past-1')
  })

  it('loadThread restores each message\'s artifact, not just its text', async () => {
    // regression: reopening a thread used to show the words but lose the graph/map/trust chip -
    // the backend now persists the artifact alongside the answer, and the hook must carry it through
    const artifact = { tool: 'map_query', confidence: 0.86, incidents: [{ lat: 1, lon: 2 }] }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          messages: [
            { role: 'user', content: 'map it' },
            { role: 'assistant', content: 'here it is', artifact },
          ],
        }),
      }),
    )
    const { result } = renderHook(() => useChatStream())
    await act(async () => result.current.loadThread('past-1'))
    expect(result.current.messages[0].artifact).toBeUndefined() // the user turn never has one
    expect(result.current.messages[1].artifact).toEqual(artifact)
  })

  it('a slow restore for an old thread cannot overwrite a newer one', async () => {
    // regression: switching threads quickly must not let the slower response win
    let resolveA: (v: unknown) => void = () => {}
    const fetchMock = vi.fn((url: string) => {
      if (url === '/threads/A') return new Promise((r) => (resolveA = r)) // stalls
      if (url === '/threads/B')
        return Promise.resolve({ ok: true, json: async () => ({ messages: [{ role: 'user', content: 'from B' }] }) })
      return Promise.resolve({ ok: true, json: async () => ({ messages: [] }) }) // mount restore
    })
    vi.stubGlobal('fetch', fetchMock)
    const { result } = renderHook(() => useChatStream())
    await act(async () => {})

    act(() => result.current.loadThread('A'))
    act(() => result.current.loadThread('B'))
    await act(async () => {}) // B resolves
    expect(result.current.messages.map((m) => m.content)).toEqual(['from B'])

    await act(async () => {
      resolveA({ ok: true, json: async () => ({ messages: [{ role: 'user', content: 'from A' }] }) })
    })
    expect(result.current.messages.map((m) => m.content)).toEqual(['from B']) // stale A ignored
    expect(result.current.threadId).toBe('B')
  })

  it('a pending restore cannot clobber a turn the user already started', async () => {
    let resolveRestore: (v: unknown) => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise((r) => (resolveRestore = r))), // the loadThread restore stalls
    )
    ;(streamChat as Mock).mockReturnValue(new Promise<void>(() => {}))
    const { result } = renderHook(() => useChatStream())

    act(() => result.current.loadThread('slow-thread'))
    act(() => result.current.send('fresh question'))
    expect(result.current.messages[0].content).toBe('fresh question')

    await act(async () => {
      resolveRestore({ ok: true, json: async () => ({ messages: [{ role: 'user', content: 'stale history' }] }) })
    })
    // the late restore must not replace the in-progress conversation
    expect(result.current.messages.map((m) => m.content)).toEqual(['fresh question', ''])
  })
})

describe('useChatStream history cap', () => {
  it('sends at most the newest 20 turns (backend rejects more with 422)', async () => {
    // a restored thread with 30 messages: the 31st ask must not blow the ChatRequest limit
    const long = Array.from({ length: 30 }, (_, i) => ({
      role: i % 2 === 0 ? 'user' : 'assistant',
      content: `m${i}`,
    }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ messages: long }) }))
    let historySeen: { role: string; content: string }[] = []
    ;(streamChat as Mock).mockImplementation((_q, h) => {
      historySeen = h
      return Promise.resolve()
    })

    const { result } = renderHook(() => useChatStream())
    await act(async () => result.current.loadThread('big')) // reopen the long thread from History
    expect(result.current.messages).toHaveLength(30)

    await act(async () => result.current.send('next question'))
    expect(historySeen).toHaveLength(20)
    expect(historySeen[0].content).toBe('m10') // the newest 20, not the oldest
    expect(historySeen[19].content).toBe('m29')
  })
})
