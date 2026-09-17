import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { GraphView } from './GraphView'
import type { SubGraph } from '../../types/contract'

vi.mock('@neo4j-nvl/react', () => ({
  InteractiveNvlWrapper: () => <div data-testid="nvl-graph" />,
}))

vi.mock('../../lib/entityInfo', () => ({
  useEntityInfo: () => () => '',
}))

const sampleGraph: SubGraph = {
  nodes: [
    { id: 'n1', labels: ['Shipment'], caption: 'SHP-1', properties: {} },
    { id: 'n2', labels: ['Policy'], caption: 'Policy-1', properties: {} },
  ],
  relationships: [{ id: 'r1', from: 'n1', to: 'n2', type: 'GOVERNED_BY' }],
}

describe('GraphView entity legend (I03)', () => {
  beforeEach(() => {
    localStorage.setItem('agentx-language', 'ar')
  })

  afterEach(() => {
    localStorage.removeItem('agentx-language')
  })

  it('shows translated entity labels in the legend when Arabic is active', () => {
    render(
      <ThemeProvider>
        <LanguageProvider>
          <div style={{ width: 600, height: 400 }}>
            <GraphView graph={sampleGraph} />
          </div>
        </LanguageProvider>
      </ThemeProvider>,
    )

    expect(screen.getByText('الشحنة')).toBeTruthy()
    expect(screen.getByText('سياسة الخدمة')).toBeTruthy()
    expect(screen.queryByText(/^Shipment$/)).toBeNull()
    expect(screen.queryByText(/^Policy$/)).toBeNull()
  })
})
