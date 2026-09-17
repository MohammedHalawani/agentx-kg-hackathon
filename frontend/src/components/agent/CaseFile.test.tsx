import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { fireEvent } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { CaseFile } from './CaseFile'
import type { CaseFile as CaseFileData } from '../../types/agent'

vi.mock('@neo4j-nvl/react', () => ({
  InteractiveNvlWrapper: () => <div data-testid="nvl-graph" />,
}))
vi.mock('../../lib/entityInfo', () => ({ useEntityInfo: () => () => '' }))
vi.mock('./ShipmentMap', () => ({ ShipmentMap: () => <div data-testid="shipment-map" /> }))

const data: CaseFileData = {
  graph: {
    nodes: [
      { id: 'n1', labels: ['Shipment'], caption: 'SHP-1042', properties: {} },
      { id: 'n2', labels: ['Customer'], caption: 'دانة العمري', properties: {} },
    ],
    relationships: [{ id: 'r1', from: 'n1', to: 'n2', type: 'ORDERED_BY' }],
  },
  route: { origin: null, points: [{ lat: 24.7, lng: 46.7, kind: 'delivery' }] },
}

describe('CaseFile full-screen panels', () => {
  beforeEach(() => localStorage.setItem('agentx-language', 'en'))
  afterEach(() => localStorage.removeItem('agentx-language'))

  const renderCaseFile = () =>
    render(
      <ThemeProvider>
        <LanguageProvider>
          <div style={{ width: 600, height: 400 }}>
            <CaseFile data={data} />
          </div>
        </LanguageProvider>
      </ThemeProvider>,
    )

  it('offers a full-screen button on the graph and the map panel', () => {
    renderCaseFile()
    expect(screen.getAllByRole('button', { name: 'Open full screen' })).toHaveLength(2)
  })

  it('opens the graph full screen and keeps exactly one copy mounted', async () => {
    renderCaseFile()
    expect(screen.getAllByTestId('nvl-graph')).toHaveLength(1)

    fireEvent.click(screen.getAllByRole('button', { name: 'Open full screen' })[0])

    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    // the graph moved into the dialog rather than being duplicated behind it
    expect(screen.getAllByTestId('nvl-graph')).toHaveLength(1)
    expect(screen.getByRole('dialog').querySelector('[data-testid="nvl-graph"]')).toBeTruthy()
  })

  it('closes again from the dialog, returning the graph to the pane', async () => {
    renderCaseFile()
    fireEvent.click(screen.getAllByRole('button', { name: 'Open full screen' })[0])
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'Close full screen' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(screen.getAllByTestId('nvl-graph')).toHaveLength(1)
  })

  it('keeps the panel title and node count in the expanded header', async () => {
    renderCaseFile()
    fireEvent.click(screen.getAllByRole('button', { name: 'Open full screen' })[0])
    await waitFor(() => expect(screen.getByRole('dialog')).toBeTruthy())
    const dialog = screen.getByRole('dialog')
    expect(dialog.textContent).toContain('SHP-1042')
    expect(dialog.textContent).toContain('2 nodes · 1 links')
  })
})
