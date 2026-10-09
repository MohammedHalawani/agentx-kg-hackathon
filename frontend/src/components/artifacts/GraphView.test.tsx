import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { GraphView } from './GraphView'
import type { SubGraph } from '../../types/contract'

vi.mock('@neo4j-nvl/react', () => ({
  InteractiveNvlWrapper: ({nodes,rels}:{nodes:typeof rendered.nodes;rels:typeof rendered.rels}) => { rendered.nodes=nodes;rendered.rels=rels;return <div data-testid="nvl-graph" /> },
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

const rendered = vi.hoisted(() => ({ nodes: [] as {id:string;activated?:boolean;disabled?:boolean}[], rels: [] as {disabled?:boolean;width?:number}[] }))

describe('GraphView entity legend (I03)', () => {
  it('emphasizes only selected evidence and relationships while retaining the bounded graph', () => {
    const {rerender}=render(<ThemeProvider><LanguageProvider><GraphView graph={sampleGraph} highlightedIds={['n1']} /></LanguageProvider></ThemeProvider>)
    expect(rendered.nodes.find(n=>n.id==='n1')).toMatchObject({activated:true,disabled:false})
    expect(rendered.nodes.find(n=>n.id==='n2')).toMatchObject({activated:false,disabled:true})
    expect(rendered.rels[0]).toMatchObject({disabled:true,width:1})
    rerender(<ThemeProvider><LanguageProvider><GraphView graph={sampleGraph} highlightedIds={['n1','n2']} /></LanguageProvider></ThemeProvider>)
    expect(rendered.nodes).toHaveLength(2)
    expect(rendered.rels[0]).toMatchObject({disabled:false,width:2})
  })
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
