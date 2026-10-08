import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { OperationsCaseDetail } from './OperationsCaseDetail'
import type { ShipmentDetail } from '@/contracts/caseDetail'
const mock = vi.hoisted(() => ({ post: vi.fn(), refetch: vi.fn(), data: { case_id: 'CASE-1', shipment_id: 'DEMO-1', workflow_state: 'AWAITING_APPROVAL', state_version: 3, recommendation_id: 'REC-1', evidence: { nodes: [], edges: [] }, reasoning: { workflow_state: 'OPEN' } } as ShipmentDetail }))
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ data: mock.data, loading: false, error: null, refetch: mock.refetch }) }))
vi.mock('@/lib/operationsClient', () => ({ operationsPost: mock.post }))
vi.mock('@/components/artifacts/Graph', () => ({ Graph: () => <div>Evidence graph</div> }))
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); mock.post.mockResolvedValue({}); mock.data.workflow_state = 'AWAITING_APPROVAL'; mock.data.reasoning = { workflow_state: 'OPEN' } })
describe('Case lifecycle authority', () => {
  it('uses ledger state rather than fresh inferred OPEN and approves without resolving', async () => {
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="DEMO-1" onBack={() => undefined} /></LanguageProvider>)
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
    render(<LanguageProvider><OperationsCaseDetail shipmentId="DEMO-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText(/Evidence only/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('does not default an observed result to success', () => {
    mock.data.workflow_state = 'AWAITING_OUTCOME'
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="DEMO-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByRole('button', { name: 'Record observed outcome' }).hasAttribute('disabled')).toBe(true)
    expect(mock.post).not.toHaveBeenCalled()
  })
})
