import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { LanguageProvider } from '@/components/i18n/LanguageProvider'
import { OperationsCaseDetail } from './OperationsCaseDetail'
import type { Diagnosis, RuleSignals, ShipmentDetail } from '@/contracts/caseDetail'
const mock = vi.hoisted(() => ({ post: vi.fn(), refetch: vi.fn(), data: { case_id: 'CASE-1', shipment_id: 'SYN-1', workflow_state: 'AWAITING_APPROVAL', state_version: 3, recommendation_id: 'REC-1', evidence: { nodes: [], edges: [] } } as ShipmentDetail }))
const diagnosis = (over: Partial<Diagnosis> = {}): Diagnosis => ({ available: true, reason: null, source: 'agent_investigation', run_id: 'SYN-OPS-RUN-0123456789ab', as_of: '2026-09-11T14:01:00Z', investigated_at: '2026-09-11T14:02:00Z', primary_cause: 'DELAYED_SYNC', confidence: 'medium', summary: 'Buffered scans from the depot handheld explain the missing receipt.', hypotheses: [{ cause: 'DELAYED_SYNC', status: 'supported', assessment: 'The handheld stopped reporting.', supporting_evidence_ids: ['SCAN'] }, { cause: 'UNRECONCILED_CUSTODY', status: 'refuted', supporting_evidence_ids: [] }], missing_evidence: [], requires_physical_check: false, tool_calls: 4, snapshot_superseded: false, language: 'en', ...over })
const signals = (codes: string[], ids: string[] = []): RuleSignals => ({ kind: 'rule_signals', is_diagnosis: false, source: 'deterministic_evidence_rules', as_of: '2026-09-12T08:00:00Z', signals: codes.map(code => ({ code, evidence_ids: ids, summary_en: 'Rule text.' })), expected_vs_actual: [] })
vi.mock('@/hooks/useFetch', () => ({ useFetch: () => ({ data: mock.data, loading: false, error: null, refetch: mock.refetch }) }))
vi.mock('@/lib/operationsClient', () => ({ operationsPost: mock.post }))
const pipeline = vi.hoisted(() => ({ live: null as null | { events: []; status: string; workflow_state: string; state_version: number; run_id?: string } }))
vi.mock('@/hooks/useCasePipeline', () => ({ useCasePipeline: () => ({ live: pipeline.live, unavailable: false }) }))
vi.mock('@/components/artifacts/Graph', () => ({ Graph: ({ highlightedIds }: { highlightedIds?: string[] }) => <div data-testid="highlighted-graph" data-ids={highlightedIds?.join(',')}>Evidence graph</div> }))
vi.mock('@/components/operations/ShipmentRouteMap', () => ({ ShipmentRouteMap: ({ highlightedIds }: { highlightedIds?:string[] }) => <div data-testid="highlighted-map" data-ids={highlightedIds?.join(',')}>Route evidence preview</div> }))
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); pipeline.live = null; mock.data.run = undefined; mock.data.executions = undefined; mock.data.last_run_id = undefined; mock.post.mockResolvedValue({}); mock.data.workflow_state = 'AWAITING_APPROVAL'; mock.data.diagnosis = undefined; mock.data.rule_signals = undefined; mock.data.outcome = null; mock.data.recommendation = { action_en: 'Compare bound custody evidence' }; mock.data.pipeline = undefined; mock.data.synthetic = true; mock.data.evidence = { nodes: [], edges: [] } })
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
    mock.data.rule_signals = { kind: 'rule_signals', is_diagnosis: false, source: 'deterministic_evidence_rules', as_of: '2026-09-11T14:01:00Z', signals: [], expected_vs_actual: [] }
    render(<LanguageProvider><OperationsCaseDetail shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText(/Evidence only/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start investigation' })).toBeNull()
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('offers no success flag: the operator can only ask the independent verifier to check', async () => {
    mock.data.workflow_state = 'AWAITING_OUTCOME'
    mock.data.executions = [{ action_type: 'REQUEST_RESCAN', authority: 'AUTO_POLICY', status: 'ACKNOWLEDGED', receipt_ref: 'synthetic_operational_simulator:X' }]
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Executed with a receipt · verification pending')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Record observed outcome' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Ask the verifier to check now' }))
    await waitFor(() => expect(mock.post).toHaveBeenCalledWith('/cases/CASE-1/outcomes', expect.not.objectContaining({ success: expect.anything() })))
  })
  it('lets a person close a human-investigation case only with a finding and attached evidence', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByRole('button', { name: 'Record human-verified finding' }).hasAttribute('disabled')).toBe(true)
  })
  it('keeps a verified action unresolved while the exception remains, and names what is still present', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.executions = [{ action_type: 'REQUEST_DEVICE_SYNC', authority: 'AUTO_POLICY', status: 'ACKNOWLEDGED' }]
    mock.data.outcome = { verification_status: 'VERIFIED', success: true, exception_cleared: false, remaining_symptoms: ['MANIFEST_CUSTODY_CONFLICT'] }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Action verified, but the exception remains · unresolved, with a person')).toBeTruthy()
    expect(screen.getByText(/Still present:/)).toBeTruthy()
    expect(screen.queryByText('Verified by independent evidence')).toBeNull()
    mock.data.executions = undefined
  })
  it('does not call a person\'s parcel-not-found finding closed', () => {
    mock.data.workflow_state = 'ESCALATED'
    mock.data.outcome = { verification_status: 'HUMAN_VERIFIED', success: false, outcome_type: 'parcel_not_found', verifier_id: 'SYN-OPERATOR-LOCAL' }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('A person’s verified finding: not resolved · escalated')).toBeTruthy()
    expect(screen.queryByText('Closed by a person with attached evidence (human-verified)')).toBeNull()
  })
  it('shows an unavailable independent review as unavailable, never as a passed safety review', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.review = { verdict: 'review_unavailable', model_verdict: 'UNAVAILABLE', degraded: true, summary_en: 'Independent model review could not be completed; automatic execution is blocked and a person must review.' }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Independent review unavailable — routed to a person')).toBeTruthy()
    expect(screen.getByText('Human review required — the independent review could not be completed.')).toBeTruthy()
    expect(screen.queryByText('Safety review passed')).toBeNull()
    expect(screen.getByTestId('review-verdict').getAttribute('data-verdict')).toBe('review_unavailable')
    mock.data.review = undefined
  })
  it('offers no approval for an action only a person can carry out', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.recommendation = { action_en: 'Physically locate the parcel', action_type: 'PHYSICAL_CUSTODY_CHECK', risk_class: 'HUMAN_REVIEW', approvable: false, approval_rule: 'AUTH-12-human-review-action' }
    mock.data.recommendation_id = 'REC-1'
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByRole('button', { name: 'Approve action' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByTestId('approval-blocked').textContent).toContain('A person carries out this action')
  })
  it('names the recorded reason a case is with a person, not a fixed evidence-conflict line', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    for (const [rule, text] of [
      ['AUTH-04-contractor-custody', /contractor or independent driver/],
      ['AUTH-14-symptom-floor', /observed symptom reserves this case/],
      ['AUTH-23-physical-check-requested', /asked for a physical check/],
      ['AUTH-06-evidence-conflict', /evidence conflict remains/],
      ['AUTH-99-something-new', /see the recorded authority decision/],
    ] as const) {
      mock.data.run = { result: { authority: { rule_id: rule, risk_class: 'HUMAN_REVIEW' } } }
      const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
      expect(screen.getByTestId('human-reason').textContent).toMatch(text)
      if (rule !== 'AUTH-06-evidence-conflict') expect(screen.getByTestId('human-reason').textContent).not.toMatch(/evidence conflict/)
      unmount()
    }
    mock.data.outcome = { verification_status: 'VERIFIED', success: true, exception_cleared: false, remaining_symptoms: ['DELIVERY_ATTEMPT_FAILED'] }
    const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('human-reason').textContent).toMatch(/verified, but the exception remains/)
    unmount()
    mock.data.outcome = null
    mock.data.executions = [{ action_type: 'REQUEST_RESCAN', authority: 'OPERATOR_APPROVAL', status: 'REFUSED', permission_rule: 'AUTH-20-approval-context-stale' }]
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('human-reason').textContent).toMatch(/refused the action/)
  })
  it('shows no review or diagnosis as current while a newer investigation runs', () => {
    mock.data.workflow_state = 'AWAITING_APPROVAL'
    mock.data.last_run_id = 'SYN-OPS-RUN-OLD'
    mock.data.review = { verdict: 'accept', reason_code: 'MODEL_ACCEPT', feedback: 'Supported by the cited scans.' }
    mock.data.diagnosis = diagnosis({ run_id: 'SYN-OPS-RUN-OLD' })
    mock.data.pipeline = { topology: { engine: 'langgraph', mode: 'agent_tool_loop', nodes: ['extract'], edges: [], retry_limit: 2 }, source: 'recorded_stage_events', status: 'REVIEWED', events: [] }
    const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('review-verdict')).toBeTruthy()
    expect(screen.getByTestId('diagnosis-primary').textContent).toBe('Delayed device synchronization')
    unmount()
    pipeline.live = { events: [], status: 'RUNNING', workflow_state: 'INVESTIGATING', state_version: 9, run_id: 'SYN-OPS-RUN-NEW' }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.queryByTestId('review-verdict')).toBeNull()
    expect(screen.queryByText('Supported by the cited scans.')).toBeNull()
    expect(screen.getByTestId('diagnosis-absent').textContent).toMatch(/An investigation is running now/)
    mock.data.review = undefined
  })
  it('explains each approval refusal the backend recheck returns', () => {
    mock.data.recommendation_id = 'REC-1'
    for (const [state, rule, text] of [
      ['AWAITING_APPROVAL', 'AUTH-20-approval-context-stale', /changed after this recommendation/],
      ['HUMAN_REVIEW', 'AUTH-21-human-investigation-required', /only evidence-gathering requests can be approved/],
      ['AWAITING_APPROVAL', 'AUTH-22-rules-only-proposal', /rule checks alone/],
      ['AWAITING_APPROVAL', 'AUTH-13-prohibited', /never executed by the system/],
    ] as const) {
      mock.data.workflow_state = state
      mock.data.recommendation = { action_en: 'Request a rescan', action_type: 'REQUEST_RESCAN', approvable: false, approval_rule: rule }
      const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
      expect(screen.getByRole('button', { name: 'Approve action' }).hasAttribute('disabled')).toBe(true)
      expect(screen.getByTestId('approval-blocked').textContent).toMatch(text)
      unmount()
    }
  })
  it('says a refused or unacknowledged execution was not dispatched or not accepted, never authorized', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.outcome = null
    mock.data.executions = [{ action_type: 'REQUEST_RESCAN', authority: 'AUTO_POLICY', status: 'REFUSED', permission_rule: 'AUTH-18-auto-not-decided' }]
    const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Refused by the authority policy · nothing was dispatched')).toBeTruthy()
    expect(screen.getByText('AUTH-18-auto-not-decided')).toBeTruthy()
    expect(screen.queryByText('Authority policy (automatic)')).toBeNull()
    unmount()
    mock.data.executions = [{ action_type: 'RETURN_TO_SENDER', authority: 'OPERATOR_APPROVAL', status: 'NOT_ACKNOWLEDGED' }]
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByText('Not acknowledged by any field system · nothing to verify, with a person')).toBeTruthy()
    mock.data.executions = undefined
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

  it('defaults to Auto stage focus, then keeps an explicit manual choice for the session', () => {
    sessionStorage.clear()
    const { unmount } = render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    const layout = () => document.querySelector('[data-focus]')!.getAttribute('data-focus')
    expect(screen.getByRole('radio', { name: 'Auto' }).getAttribute('aria-checked')).toBe('true')
    expect(screen.getByText(/This stage reads best on the|Auto follows the investigation stage/)).toBeTruthy()
    fireEvent.click(screen.getByRole('radio', { name: 'Map focus' }))
    expect(layout()).toBe('map')
    expect(screen.queryByText(/This stage reads best/)).toBeNull()
    unmount()
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(layout()).toBe('map')
    expect(mock.post).not.toHaveBeenCalled()
  })
  it('shows the recorded reason for a rejection in Arabic and never a vehicle-GPS story nobody wrote', () => {
    localStorage.setItem('agentx-language', 'ar')
    mock.data.workflow_state = 'ESCALATED'
    mock.data.recommendation = { action_en: 'Request a package rescan at the current facility.', action_ar: 'طلب إعادة مسح الطرد في المنشأة الحالية.' }
    mock.data.review = { verdict: 'reject', reason_code: 'MODEL_REVISE', model_verdict: 'REVISE', feedback: 'Re-check the scan device.', summary_en: 'Re-check the scan device.', summary_ar: 'طلب المراجع المستقل تعديل المقترح؛ ملاحظاته مسجلة بنصها الأصلي.' }
    mock.data.pipeline = { topology: { engine: 'langgraph', mode: 'agent_tool_loop', nodes: ['recommend', 'review'], edges: [], retry_limit: 2 }, source: 'recorded_stage_events', status: 'REVIEWED', events: [
      { sequence: 1, stage: 'recommend', status: 'COMPLETED', iteration: 0, recorded_at: '2026-10-09T01:00:00Z', evidence_as_of: '2026-09-11T14:01:00Z', output: { proposal: { action_en: 'Request a package rescan at the current facility.' } } },
      { sequence: 2, stage: 'review', status: 'REJECTED', iteration: 1, recorded_at: '2026-10-09T01:00:01Z', evidence_as_of: '2026-09-11T14:01:00Z', output: { verdict: 'reject', feedback: 'Re-check the scan device.', summary_ar: 'طلب المراجع المستقل تعديل المقترح؛ ملاحظاته مسجلة بنصها الأصلي.' } },
    ] }
    mock.data.run = { result: { trace: [{ iteration: 0, mode: 'gpt-oss', review: { verdict: 'reject', feedback: 'Re-check the scan device.' }, proposal: { action_en: 'Request a package rescan at the current facility.' } }] } }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(document.body.textContent).toContain('طلب المراجع المستقل تعديل المقترح')
    fireEvent.click(screen.getByRole('button', { name: /مراجعة السلامة/ }))
    expect(screen.getAllByText(/طلب المراجع المستقل تعديل المقترح/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('tab', { name: /المراجعة/ }))
    // A legacy trace entry without an Arabic summary shows the reviewer's own words, not an invented reason.
    expect(screen.getByTestId('review-round-reason').textContent).toBe('Re-check the scan device.')
    expect(document.body.textContent).not.toContain('موقع المركبة')
    expect(document.body.textContent).not.toMatch(/GPS/)
    localStorage.clear(); mock.data.review = undefined; mock.data.run = undefined
  })
  it('shows a review with no proposal as such, not as a rejection', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.review = { verdict: 'no_proposal', reason_code: 'INVESTIGATOR_UNAVAILABLE', feedback: 'The investigation agent did not reach a valid conclusion; there is no proposal to review and a person must review the case.' }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('review-verdict').getAttribute('data-verdict')).toBe('no_proposal')
    expect(screen.getByText('No proposal to review')).toBeTruthy()
    expect(screen.queryByText(/Recommendation rejected/)).toBeNull()
    expect(document.body.textContent).not.toMatch(/GPS/)
    mock.data.review = undefined
  })
  it('shows the agent investigation as what happened, with its run and snapshot, and rule signals apart', () => {
    mock.data.workflow_state = 'AWAITING_APPROVAL'
    mock.data.diagnosis = diagnosis()
    mock.data.rule_signals = signals(['UNRECONCILED_CUSTODY'])
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('diagnosis-primary').textContent).toBe('Delayed device synchronization')
    expect(screen.getByTestId('diagnosis-provenance').textContent).toContain('confidence medium')
    expect(screen.getByTestId('diagnosis-provenance').textContent).toContain('56789ab')
    expect(screen.getByTestId('rule-signals').textContent).toMatch(/not a diagnosis/)
    expect(screen.getByTestId('rule-signals').textContent).toContain('Unreconciled custody')
    fireEvent.click(screen.getByRole('tab', { name: 'Diagnosis' }))
    expect(screen.getAllByTestId('diagnosis-hypothesis').map(h => h.textContent)).toEqual([expect.stringContaining('Delayed device synchronization'), expect.stringContaining('refuted')])
    expect(screen.getByTestId('rule-signals-panel').textContent).toContain('Rule signals — not a diagnosis')
  })
  it('never fills an absent diagnosis from rule signals', () => {
    mock.data.workflow_state = 'HUMAN_REVIEW'
    mock.data.diagnosis = { ...diagnosis(), available: false, reason: 'no_agent_investigation', source: null, primary_cause: null, confidence: null, summary: null, hypotheses: [] }
    mock.data.rule_signals = signals(['DELIVERY_DISPUTE'], ['PROOF'])
    mock.data.evidence = { nodes: [{ id: 'PROOF', kind: 'DeliveryProof', properties: {} }], edges: [] }
    render(<LanguageProvider><OperationsCaseDetail caseId="CASE-1" shipmentId="SYN-1" onBack={() => undefined} /></LanguageProvider>)
    expect(screen.getByTestId('diagnosis-primary').textContent).toBe('No diagnosis')
    expect(screen.getByTestId('diagnosis-absent').textContent).toMatch(/No agent investigation ran/)
    expect(screen.getByTestId('rule-signals').textContent).toContain('Delivery dispute')
    fireEvent.click(screen.getByRole('tab', { name: /Evidence/ }))
    // Evidence a rule flagged is labelled as a rule check, never as cited by a diagnosis.
    expect(screen.getAllByText('Flagged by a rule check: Delivery dispute').length).toBeGreaterThan(0)
    expect(screen.queryByText(/Cited by diagnosis/)).toBeNull()
    fireEvent.click(screen.getByRole('tab', { name: 'Diagnosis' }))
    expect(within(screen.getByTestId('diagnosis-panel')).queryByText(/Delivery dispute/)).toBeNull()
  })
  it('opens Evidence on cited key evidence and focuses the graph on it without running anything', () => {
    mock.data.evidence = { nodes: [{ id: 'PROOF', kind: 'DeliveryProof', properties: {} }, { id: 'REPORT', kind: 'RecipientReport', properties: { report_code: 'NOT_RECEIVED' } }, { id: 'HUB', kind: 'Hub', properties: {} }], edges: [] }
    mock.data.diagnosis = diagnosis({ primary_cause: 'DELIVERY_DISPUTE', hypotheses: [{ cause: 'DELIVERY_DISPUTE', status: 'supported', supporting_evidence_ids: ['PROOF', 'REPORT'] }] })
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
