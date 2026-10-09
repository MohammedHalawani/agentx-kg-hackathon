import { describe, expect, it } from 'vitest'
import { activeStage, pipelineSteps, suggestedFocus } from './pipelineSteps'
import type { PipelineEvent, ShipmentDetail } from '@/contracts/caseDetail'

const ev = (sequence: number, stage: PipelineEvent['stage'], status: string, output: PipelineEvent['output'] = {}, iteration = 0): PipelineEvent =>
  ({ sequence, stage, status, iteration, recorded_at: '2026-10-09T00:00:00Z', evidence_as_of: '2026-09-11T00:00:00Z', output })
const base = (events: PipelineEvent[], extra: Partial<ShipmentDetail> = {}): ShipmentDetail => ({
  shipment_id: 'SYN-SHP-1', evidence: { nodes: [], edges: [] },
  pipeline: { topology: { engine: 'langgraph', mode: 'deterministic_evidence_rules', nodes: [], edges: [], retry_limit: 2 }, events, source: 'recorded_stage_events', status: 'REVIEWED' },
  ...extra,
})
const full = [
  ev(1, 'extract', 'COMPLETED'), ev(2, 'retrieve', 'COMPLETED'), ev(3, 'classify', 'COMPLETED'), ev(4, 'retrieve_context', 'COMPLETED'),
  ev(5, 'recommend', 'COMPLETED'), ev(6, 'review', 'REJECTED', { verdict: 'reject' }), ev(7, 'recommend', 'COMPLETED', {}, 1),
  ev(8, 'review', 'COMPLETED', { verdict: 'accept' }, 1), ev(9, 'writeback', 'COMPLETED', { workflow_state: 'HUMAN_REVIEW' }),
]

describe('Compact pipeline steps over recorded LangGraph events', () => {
  it('maps eight display steps, keeps the review revision loop and routes to the recorded human gate', () => {
    const steps = pipelineSteps(base(full, { workflow_state: 'HUMAN_REVIEW' }))
    expect(steps.map(s => s.key)).toEqual(['collect', 'graph', 'diagnose', 'precedent', 'recommend', 'review', 'route', 'outcome'])
    const review = steps.find(s => s.key === 'review')!
    expect(review).toMatchObject({ status: 'COMPLETED', revisions: 1 })
    expect(steps.find(s => s.key === 'route')).toMatchObject({ stage: 'writeback', status: 'HUMAN_REVIEW' })
    expect(steps.find(s => s.key === 'outcome')!.status).toBe('WAITING')
  })

  it('never shows the outcome gate complete from a recommendation, approval or unverified observation', () => {
    const accepted = full.slice(0, 8).concat(ev(9, 'writeback', 'COMPLETED', { workflow_state: 'AWAITING_APPROVAL' }))
    for (const extra of [
      { workflow_state: 'AWAITING_APPROVAL' as const },
      { workflow_state: 'AWAITING_OUTCOME' as const, decisions: [{ decision: 'approve' }] },
      { workflow_state: 'AWAITING_OUTCOME' as const, outcome: { verification_status: 'OBSERVED', success: true } },
      { workflow_state: 'RESOLVED' as const, outcome: { verification_status: 'VERIFIED', invalidated: true } },
    ]) expect(pipelineSteps(base(accepted, extra)).at(-1)!.status).not.toBe('COMPLETED')
    expect(pipelineSteps(base(accepted, { workflow_state: 'RESOLVED', outcome: { verification_status: 'VERIFIED', success: true } })).at(-1)!.status).toBe('COMPLETED')
  })

  it('shows the escalation branch only when it actually ran', () => {
    const escalated = [...full.slice(0, 5), ev(6, 'review', 'REJECTED'), ev(7, 'escalate', 'COMPLETED', { workflow_state: 'ESCALATED' })]
    expect(pipelineSteps(base(escalated)).find(s => s.key === 'route')).toMatchObject({ stage: 'escalate', status: 'ESCALATED' })
  })

  it('reports live running stages and earlier runs without timing honestly', () => {
    const live = base([ev(1, 'extract', 'COMPLETED'), ev(2, 'retrieve', 'RUNNING')])
    expect(pipelineSteps(live).map(s => s.status).slice(0, 3)).toEqual(['COMPLETED', 'RUNNING', 'QUEUED'])
    expect(activeStage(live)).toBe('retrieve')
    expect(activeStage(base(full))).toBe('classify')
    const earlier = base([], { run: { mode: 'deterministic_evidence_rules' } })
    earlier.pipeline!.source = 'earlier_run'
    expect(pipelineSteps(earlier).slice(0, 7).every(s => s.status === 'UNRECORDED')).toBe(true)
  })

  it('suggests the map only for spatial stages', () => {
    expect(['extract', 'classify'].map(s => suggestedFocus(s as 'extract'))).toEqual(['map', 'map'])
    expect(['retrieve_context', 'review', 'writeback', 'outcome'].map(s => suggestedFocus(s as 'review'))).toEqual(['graph', 'graph', 'graph', 'graph'])
  })
})

import { stageFocus } from './pipelineSteps'
describe('stageFocus (Auto layout)', () => {
  it('follows the evidence type of each stage', () => {
    expect(stageFocus('extract', ['TRAFFIC_DELAY'])).toBe('balanced')
    expect(stageFocus('retrieve', ['TRAFFIC_DELAY'])).toBe('graph')
    expect(stageFocus('classify', ['TRAFFIC_DELAY'])).toBe('map')
    expect(stageFocus('classify', ['DELIVERY_DISPUTE'])).toBe('graph')
    expect(stageFocus('retrieve_context', ['ADDRESS_CONFLICT'])).toBe('graph')
    expect(stageFocus('recommend', ['ADDRESS_CONFLICT'])).toBe('balanced')
    expect(stageFocus('review', [])).toBe('graph')
    expect(stageFocus('writeback', ['UNRECONCILED_CUSTODY'])).toBe('map')
    expect(stageFocus('outcome', ['TRAFFIC_DELAY'])).toBe('balanced')
  })
})
