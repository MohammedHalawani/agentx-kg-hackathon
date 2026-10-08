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
  useFetch: (url: string) => ({
    data: url.startsWith('/cases/queue') ? {
      items: [
        {
          case_id: 'f1',
          shipment_id: 'SHP-0001',
          category: 'address_conflict',
          city: 'Riyadh',
          courier: 'Courier A',
          issue_summary: 'Sample complaint text',
          priority: 'medium', workflow_state: 'OPEN',
        },
      ], filtered_total: 1, next_cursor: null, previous_cursor: null, metadata: { buckets: { OPEN: 1 }, filter_choices: { city: ['Riyadh'], cause: ['address_conflict'] } },
    } : { synthetic: true, demo: true, as_of: '2026-10-08T08:00:00Z', worker: { state: 'paused', concurrency: 1, processed_count: 0, active_case_id: null }, simulator: { state: 'paused', speed: 1, event_count: 0 }, notifications: { mode: 'dry_run', external_calls: 0 } },
    loading: false,
    error: null, refetch: vi.fn(),
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
    expect(screen.getByText(/Operations intake|استقبال العمليات/)).toBeTruthy()
  })

  it('labels simulation panel as demo-only', () => {
    renderIntake()
    expect(screen.getAllByText(/DEMO — synthetic operational data/i).length).toBeGreaterThan(0)
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
    expect(screen.getAllByText('تعارض في العنوان').length).toBeGreaterThan(0)
    expect(screen.queryByText('address conflict')).toBeNull()
  })
})

describe('IntakeView active-run lifecycle', () => {
  it('uses text-muted-foreground in running pipeline trace (no text-muted)', () => {
    mockStream.busy = true
    mockStream.complaint = 'Wrong address delivered'
    mockStream.stages = [sampleStage]

    renderIntake()

    expect(screen.getByText('Evidence collected')).toBeTruthy()
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

  it('renders a pending recommendation without claiming execution', () => {
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

    expect(screen.getByText(/Recommendation recorded/i)).toBeTruthy()
    expect(screen.queryByText(/^Executed$/i)).toBeNull()
    expect(screen.getByTestId('case-graph')).toBeTruthy()
    expect(screen.getByTestId('shipment-map')).toBeTruthy()
    expect(document.querySelector('.text-muted')).toBeNull()
  })
})
