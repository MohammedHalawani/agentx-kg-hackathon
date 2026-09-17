import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { IntakeView } from './IntakeView'
import type { CaseFile, FinalResult, Stage } from '../../types/agent'

const mockStream = vi.hoisted(() => ({
  stages: [] as Stage[],
  final: null as FinalResult | null,
  caseFile: null as CaseFile | null,
  busy: false,
  error: null as string | null,
  complaint: null as string | null,
  run: vi.fn(),
  stop: vi.fn(),
  reset: vi.fn(),
}))

vi.mock('../../hooks/useComplaintStream', () => ({
  useComplaintStream: () => mockStream,
}))

vi.mock('../../hooks/useFetch', () => ({
  useFetch: () => ({
    data: {
      cases: [
        {
          failure_id: 'f1',
          shipment_id: 'SHP-0001',
          category: 'address_conflict',
          city: 'Riyadh',
          courier: 'Courier A',
          text: 'Sample complaint text',
        },
      ],
    },
    loading: false,
    refetch: vi.fn(),
  }),
}))

vi.mock('../artifacts/Graph', () => ({
  Graph: ({ graph }: { graph: { nodes: unknown[] } }) => (
    <div data-testid="case-graph">{graph.nodes.length} nodes</div>
  ),
}))

vi.mock('../agent/ShipmentMap', () => ({
  ShipmentMap: () => <div data-testid="shipment-map">map</div>,
}))

const sampleStage: Stage = {
  stage: 'extract',
  label: 'Extract entities',
  lane: 'Retrieval',
  arabic: 'استخراج',
  is_agent: false,
  loop: 0,
  detail: {
    shipment_id: 'SHP-0001',
    city: 'Riyadh',
    courier: 'Courier A',
  },
}

const sampleCaseFile: CaseFile = {
  graph: {
    nodes: [{ id: 's1', labels: ['Shipment'], caption: 'SHP-0001', properties: {} }],
    relationships: [],
  },
  route: {
    origin: { lat: 24.7, lng: 46.7, kind: 'warehouse', city: 'Riyadh' },
    points: [{ lat: 24.8, lng: 46.8, kind: 'delivery', city: 'Riyadh' }],
  },
}

function renderIntake() {
  return render(
    <ThemeProvider>
      <LanguageProvider>
        <IntakeView />
      </LanguageProvider>
    </ThemeProvider>,
  )
}

beforeEach(() => {
  mockStream.stages = []
  mockStream.final = null
  mockStream.caseFile = null
  mockStream.busy = false
  mockStream.error = null
  mockStream.complaint = null
})

describe('IntakeView metadata contrast (H01)', () => {
  it('uses text-muted-foreground for count, description, and case metadata', () => {
    renderIntake()
    const mutedEls = document.querySelectorAll('.text-muted-foreground')
    expect(mutedEls.length).toBeGreaterThanOrEqual(3)
    expect(document.querySelector('.text-muted')).toBeNull()
    expect(screen.getByText(/awaiting decision/i).className).toContain('text-muted-foreground')
  })

  it('pairs accent hover background with accent-foreground on case buttons (H02)', () => {
    renderIntake()
    const caseBtn = screen.getByText('Sample complaint text').closest('button')
    expect(caseBtn?.className).toContain('hover:bg-accent')
    expect(caseBtn?.className).toContain('hover:text-accent-foreground')
    expect(caseBtn?.className).toContain('group')
  })
})

describe('IntakeView Arabic root causes (I02)', () => {
  beforeEach(() => {
    localStorage.setItem('agentx-language', 'ar')
  })

  afterEach(() => {
    localStorage.removeItem('agentx-language')
  })

  it('shows Arabic category metadata on idle case cards', () => {
    renderIntake()
    expect(screen.getByText('تعارض في العنوان')).toBeTruthy()
    expect(screen.queryByText('address conflict')).toBeNull()
  })
})

describe('IntakeView active-run lifecycle', () => {
  it('uses text-muted-foreground in running pipeline trace (no text-muted)', () => {
    mockStream.busy = true
    mockStream.complaint = 'Wrong address delivered'
    mockStream.stages = [sampleStage]

    renderIntake()

    expect(screen.getByText('Extract entities')).toBeTruthy()
    expect(document.querySelector('.text-muted')).toBeNull()
    expect(document.querySelectorAll('.text-muted-foreground').length).toBeGreaterThan(0)
    expect(screen.getByText(/working/i)).toBeTruthy()
  })

  it('renders error banner without text-muted regressions', () => {
    mockStream.busy = false
    mockStream.complaint = 'Wrong address delivered'
    mockStream.stages = [sampleStage]
    mockStream.error = 'The pipeline stream was interrupted.'

    renderIntake()

    expect(screen.getByText('The pipeline stream was interrupted.')).toBeTruthy()
    expect(document.querySelector('.text-muted')).toBeNull()
  })

  it('renders success outcome and case file evidence pane', () => {
    mockStream.busy = false
    mockStream.complaint = 'Wrong address delivered'
    mockStream.stages = [sampleStage]
    mockStream.final = {
      disposition: 'execute',
      resolution_id: 'RES-42',
      loops: 0,
      review: { verdict: 'accept' },
    }
    mockStream.caseFile = sampleCaseFile

    renderIntake()

    expect(screen.getByText(/executed/i)).toBeTruthy()
    expect(screen.getByTestId('case-graph')).toBeTruthy()
    expect(screen.getByTestId('shipment-map')).toBeTruthy()
    expect(document.querySelector('.text-muted')).toBeNull()
  })
})
