import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BrainView } from './BrainView'

// Graph renders NVL/force-graph onto a canvas, which jsdom can't do meaningfully - stub it so this
// test stays focused on BrainView's own contract: fetch on mount, refetch on the resample button.
vi.mock('../artifacts/Graph', () => ({
  Graph: ({ graph }: { graph: { nodes: unknown[] } }) => <div data-testid="graph">{graph.nodes.length} nodes</div>,
}))

afterEach(() => vi.unstubAllGlobals())

// Regression guard: the domain graph is 50k+ nodes, too large to render whole, so BrainView shows
// a random slice with a button to draw another - it must not silently stay on the first sample.
describe('BrainView resample', () => {
  it('fetches /graph on mount and again when "show another part" is clicked', async () => {
    let call = 0
    const fetchMock = vi.fn(() => {
      call += 1
      return Promise.resolve({ ok: true, json: async () => ({ nodes: [{ id: String(call) }], relationships: [] }) })
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<BrainView />)
    await waitFor(() => expect(screen.getByTestId('graph')).toBeTruthy())
    expect(fetchMock).toHaveBeenCalledWith('/graph', expect.anything())
    expect(fetchMock).toHaveBeenCalledTimes(1)

    await act(async () => fireEvent.click(screen.getByText('Show another part of the graph')))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  })
})
