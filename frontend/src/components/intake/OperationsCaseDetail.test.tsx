import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { OperationsCaseDetail } from './OperationsCaseDetail'
import type { ShipmentDetail } from '@/contracts/caseDetail'
const mock = vi.hoisted(() => ({ post: vi.fn(), refetch: vi.fn(), data: { case_id: 'CASE-1', shipment_id: 'SYN-1', workflow_state: 'AWAITING_APPROVAL', state_version: 3, recommendation_id: 'REC-1', evidence: { nodes: [], edges: [] }, reasoning: { workflow_state: 'OPEN' } } as ShipmentDetail }))
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ data: mock.data, loading: false, error: null, refetch: mock.refetch }) }))
vi.mock('@/lib/operationsClient', () => ({ operationsPost: mock.post }))
vi.mock('@/components/artifacts/Graph', () => ({ Graph: ({ highlightedIds }: { highlightedIds?: string[] }) => <div data-testid="highlighted-graph" data-ids={highlightedIds?.join(',')}>Evidence graph</div> }))
vi.mock('@/components/operations/ShipmentRouteMap', () => ({ ShipmentRouteMap: ({ highlightedIds }: { highlightedIds?:string[] }) => <div data-testid="highlighted-map" data-ids={highlightedIds?.join(',')}>Route evidence preview</div> }))
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mock.post.mockResolvedValue({}); mock.data.workflow_state = 'AWAITING_APPROVAL'; mock.data.reasoning = { workflow_state: 'OPEN' }; mock.data.outcome = null; mock.data.recommendation = { action_en: 'Compare bound custody evidence' }; mock.data.pipeline = undefined; mock.data.synthetic = true; mock.data.evidence = { nodes: [], edges: [] } })
describe('Case lifecycle authority', () => {
  it('uses ledger state rather than fresh inferred OPEN and approves without resolving', async () => {
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Approve action' }))
    await waitFor(() => expect(mock.post).toHaveBeenCalled())
    expect(mock.post.mock.calls[0][0]).toBe('/cases/CASE-1/decision')
    expect(mock.post.mock.calls[0][1]).toMatchObject({ decision: 'approve', expected_version: 3 })
    expect(mock.post.mock.calls[0][1].idempotency_key).toBeTruthy()
    expect(screen.queryByText(/^Resolved$/)).toBeNull()
  })
  it('keeps a healthy shipment with NO_EXCEPTION assessment evidence-only', () => {
    mock.data.workflow_state = undefined
    mock.data.reasoning = { workflow_state: 'NO_EXCEPTION' }
    render(<LanguageProvider><OperationsCaseDetail shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText(/Evidence only/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('does not default an observed result to success', () => {
    mock.data.workflow_state = 'AWAITING_OUTCOME'
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByRole('button', { name: 'Record observed outcome' }).hasAttribute('disabled')).toBe(true)
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('shows graph and recommendation in Overview before approval controls', () => {
    mock.data.recommendation = { action_en: 'Compare bound custody evidence' }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Evidence graph')).toBeTruthy()
    expect(screen.getByText('Compare bound custody evidence')).toBeTruthy()
    expect(screen.getByText('Compare bound custody evidence').compareDocumentPosition(screen.getByRole('button', { name: 'Approve action' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Recommendation' }))
    expect(screen.getByText('Compare bound custody evidence')).toBeTruthy()
  })
  it('lets the operator reopen a verified case through the versioned decision API', async () => {
    mock.data.workflow_state = 'RESOLVED'
    mock.data.outcome = { verification_status: 'VERIFIED', success: true }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    fireEvent.click(screen.getByRole('button', { name: 'Reopen case' }))
    await waitFor(() => expect(mock.post).toHaveBeenCalledWith('/cases/CASE-1/decision', expect.objectContaining({ decision: 'reopen', expected_version: 3 })))
    expect(screen.queryByRole('button', { name: 'Verify observed outcome' })).toBeNull()
  })
  it('pins the selected recorded stage and synchronizes its evidence across graph and map', () => {
    mock.data.evidence = { nodes: [{ id: 'SYN-1', kind: 'Shipment', properties: {} }, { id: 'PIN', kind: 'AddressVersion', properties: {} }, { id: 'PROOF', kind: 'DeliveryProof', properties: {} }], edges: [] }
    mock.data.pipeline = { topology: { engine: 'langgraph', mode: 'deterministic_evidence_rules', nodes: ['extract', 'classify', 'review'], edges: [], retry_limit: 2 }, source: 'recorded_stage_events', status: 'REVIEWED', events: [
      { sequence: 1, stage: 'extract', status: 'COMPLETED', iteration: 0, recorded_at: '2026-10-09T01:00:00Z', evidence_as_of: '2026-09-11T14:01:00Z', output: { evidence_ids: ['SYN-1'] } },
      { sequence: 2, stage: 'review', status: 'REJECTED', iteration: 1, recorded_at: '2026-10-09T01:00:01Z', evidence_as_of: '2026-09-11T14:01:00Z', output: { evidence_ids: ['PROOF'], verdict: 'reject' } },
    ] }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    fireEvent.click(screen.getByRole('button', { name: /Collect references.*Completed/ }))
    expect(screen.getByTestId('highlighted-graph').getAttribute('data-ids')).toContain('SYN-1')
    expect(screen.getByTestId('highlighted-graph').getAttribute('data-ids')).not.toContain('PROOF')
    fireEvent.click(screen.getByRole('button', { name: /Safety review.*Rejected/ }))
    expect(screen.getByTestId('highlighted-graph').getAttribute('data-ids')).toContain('PROOF')
    expect(screen.getByTestId('highlighted-map').getAttribute('data-ids')).toBe(screen.getByTestId('highlighted-graph').getAttribute('data-ids'))
    expect(screen.getByText(/reviewer rejection \/ revision/)).toBeTruthy()
    expect(document.body.textContent).not.toMatch(/DEMO|PROTOTYPE|PLACEHOLDER|chain.of.thought/i)
    expect(screen.getByText('Synthetic operational data')).toBeTruthy()
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('shows completed automatic investigation and a human decision boundary without reopening an active case', () => {
    mock.data.workflow_state='HUMAN_REVIEW'
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByRole('region',{name:'Human decision'})).toBeTruthy()
    expect(screen.getByText(/Suhail completed the investigation automatically/)).toBeTruthy()
    expect(screen.queryByRole('button',{name:'Reopen case'})).toBeNull()
    expect(screen.getByText(/select a stage to inspect evidence, never to run it/)).toBeTruthy()
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('requires an explicit versioned re-analysis command', async () => {
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(mock.post).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Re-analyze case' }))
    await waitFor(() => expect(mock.post).toHaveBeenCalledWith('/cases/CASE-1/reanalyze', expect.objectContaining({ expected_version: 3 })))
  })

  it('switches Balanced, Map and Graph focus explicitly and remembers the choice for the session', () => {
    sessionStorage.clear()
    const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    const layout = () => document.querySelector('[data-focus]')!.getAttribute('data-focus')
    expect(layout()).toBe('balanced')
    expect(screen.getByText(/This stage reads best on the route map/)).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: 'Graph focus' }))
    expect(layout()).toBe('graph')
    expect(screen.queryByText(/This stage reads best/)).toBeNull()
    unmount()
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(layout()).toBe('graph')
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('opens Evidence on cited key evidence and focuses the graph on it without running anything', () => {
    mock.data.evidence = { nodes: [{ id: 'PROOF', kind: 'DeliveryProof', properties: {} }, { id: 'REPORT', kind: 'RecipientReport', properties: { report_code: 'NOT_RECEIVED' } }, { id: 'HUB', kind: 'Hub', properties: {} }], edges: [] }
    mock.data.reasoning = { workflow_state: 'HUMAN_REVIEW', diagnoses: [{ code: 'DELIVERY_DISPUTE', evidence_ids: ['PROOF', 'REPORT'] }] }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    fireEvent.click(screen.getByRole('tab', { name: /Evidence/ }))
    expect(screen.getByRole('tab', { name: /Key evidence/ }).getAttribute('aria-selected')).toBe('true')
    expect(screen.getAllByText(/Cited by diagnosis: Delivery dispute/)).toHaveLength(2)
    expect(screen.queryByText('HUB')).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: /Full inventory/ }))
    expect(screen.getByText(/Regional hub/)).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: /Key evidence/ }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Show in graph' })[0])
    expect(screen.getByTestId('highlighted-graph').getAttribute('data-ids')).toBe('PROOF')
    expect(screen.getByText(/Highlighting 1 selected evidence/)).toBeTruthy()
    expect(mock.post).not.toHaveBeenCalled()
  })

})
