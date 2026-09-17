import { describe, expect, it, vi, beforeAll, afterAll } from 'vitest'
import { render, act } from '@testing-library/react'
import { ThemeProvider, useTheme } from '../theme/ThemeProvider'
import { LanguageProvider } from '../i18n/LanguageProvider'
import { BrainGraph } from './BrainGraph'
import type { SubGraph } from '../../types/contract'

const graphProps: { backgroundColor?: string; graphData?: unknown } = {}

vi.mock('react-force-graph-3d', () => ({
  default: (props: { backgroundColor?: string; graphData?: unknown }) => {
    graphProps.backgroundColor = props.backgroundColor
    graphProps.graphData = props.graphData
    return <div data-testid="force-graph-3d" />
  },
}))

vi.mock('./MapView', () => ({
  MapView: () => <div data-testid="map-view" />,
}))

vi.mock('../../lib/entityInfo', () => ({
  useEntityInfo: () => () => '',
}))

const sampleGraph: SubGraph = {
  nodes: [
    { id: 'n1', labels: ['Shipment'], caption: 'SHP-1', properties: {} },
    { id: 'n2', labels: ['Address'], caption: 'Addr', properties: {} },
  ],
  relationships: [{ id: 'r1', from: 'n1', to: 'n2', type: 'TO' }],
}

function ThemeToggle() {
  const { setTheme } = useTheme()
  return (
    <button type="button" onClick={() => setTheme('dark')}>
      dark
    </button>
  )
}

describe('BrainGraph theme lifecycle (E03)', () => {
  beforeAll(() => {
    document.documentElement.style.setProperty('--color-surface', '#faf9f7')
    document.documentElement.style.setProperty('--graph-1', '#3366cc')
    document.documentElement.style.setProperty('--graph-2', '#cc6633')

    // jsdom has no canvas — stub tokenHex's 1px readback so theme toggles produce distinct hexes.
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(() => {
      let fillStyle = ''
      return {
        set fillStyle(v: string) {
          fillStyle = v
        },
        get fillStyle() {
          return fillStyle
        },
        fillRect: vi.fn(),
        getImageData: () => {
          const dark = document.documentElement.classList.contains('dark')
          return { data: dark ? [17, 19, 24, 255] : [250, 249, 247, 255] }
        },
      } as unknown as CanvasRenderingContext2D
    })

    class ResizeObserverMock {
      private callback: ResizeObserverCallback
      constructor(callback: ResizeObserverCallback) {
        this.callback = callback
      }
      observe(el: Element) {
        const rect = el.getBoundingClientRect()
        const width = rect.width || 400
        const height = rect.height || 300
        queueMicrotask(() => {
          this.callback(
            [{ contentRect: { width, height } } as ResizeObserverEntry],
            this as unknown as ResizeObserver,
          )
        })
      }
      disconnect() {}
      unobserve() {}
    }
    vi.stubGlobal('ResizeObserver', ResizeObserverMock)
  })

  afterAll(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('updates backgroundColor and node colors when resolvedTheme changes without remount', async () => {
    document.documentElement.classList.remove('dark')
    document.documentElement.style.setProperty('--graph-1', '#3366cc')

    const { getByTestId, getByText, findByTestId } = render(
      <ThemeProvider>
        <LanguageProvider>
          <ThemeToggle />
          <div style={{ width: 400, height: 300 }}>
            <BrainGraph graph={sampleGraph} />
          </div>
        </LanguageProvider>
      </ThemeProvider>,
    )

    await findByTestId('force-graph-3d')

    const lightBg = graphProps.backgroundColor
    const lightNodeColor = (graphProps.graphData as { nodes: { color: string }[] }).nodes[0].color
    expect(lightBg).toBe('#faf9f7')
    expect(lightNodeColor).toBe('#3366cc')

    document.documentElement.style.setProperty('--graph-1', '#99bbff')
    await act(async () => {
      getByText('dark').click()
    })

    expect(graphProps.backgroundColor).toBe('#111318')
    const darkNodeColor = (graphProps.graphData as { nodes: { color: string }[] }).nodes[0].color
    expect(darkNodeColor).toBe('#99bbff')
    expect(darkNodeColor).not.toBe(lightNodeColor)
    expect(getByTestId('force-graph-3d')).toBeTruthy()
  })
})
