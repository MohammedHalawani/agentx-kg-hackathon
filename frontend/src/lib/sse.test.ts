import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamChat, type StreamHandlers } from './sse'

afterEach(() => vi.unstubAllGlobals())

// a minimal res.body stand-in: streamChat only needs getReader().read()
const bodyFrom = (...chunks: string[]) => {
  const queue = chunks.map((c) => new TextEncoder().encode(c))
  return {
    getReader: () => ({
      read: async () =>
        queue.length ? { done: false, value: queue.shift() } : { done: true, value: undefined },
    }),
    cancel: async () => {},
  }
}

const handlers = (): StreamHandlers => ({
  onText: vi.fn(),
  onReasoning: vi.fn(),
  onStep: vi.fn(),
  onArtifact: vi.fn(),
  onError: vi.fn(),
  onDone: vi.fn(),
})

describe('streamChat', () => {
  it('POSTs message, history and thread_id, and dispatches parsed SSE events', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: bodyFrom('event: text\ndata: {"text":"hi"}\n\nevent: done\ndata: {}\n\n'),
    })
    vi.stubGlobal('fetch', fetchMock)
    const h = handlers()

    await streamChat('a question', [{ role: 'user', content: 'earlier' }], h, undefined, 'tid-9')

    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/chat')
    expect(JSON.parse(init.body)).toEqual({
      message: 'a question',
      history: [{ role: 'user', content: 'earlier' }],
      thread_id: 'tid-9', // the memory key must actually reach the wire
    })
    expect(h.onText).toHaveBeenCalledWith('hi')
    expect(h.onDone).toHaveBeenCalled()
  })

  it('reassembles a frame split across reads (partial-chunk buffering)', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: bodyFrom('event: text\ndata: {"te', 'xt":"joined"}\n\n'),
    })
    vi.stubGlobal('fetch', fetchMock)
    const h = handlers()
    await streamChat('q', [], h)
    expect(h.onText).toHaveBeenCalledWith('joined')
  })

  it('reports a non-OK response through onError', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, body: null }))
    const h = handlers()
    await streamChat('q', [], h)
    expect(h.onError).toHaveBeenCalledWith('Request failed (422)')
  })
})
