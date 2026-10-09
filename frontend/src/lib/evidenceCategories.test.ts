import { describe, expect, it } from 'vitest'
import { evidenceCategories, mappedEvidenceIds } from './evidenceCategories'
import type { ShipmentDetail } from '@/contracts/caseDetail'

const n = (id: string, kind: string, properties: Record<string, unknown> = {}) => ({ id, kind, properties })
const detail: ShipmentDetail = {
  shipment_id: 'SYN-SHP-1',
  evidence: {
    nodes: [n('SHP', 'Shipment'), n('PROOF', 'DeliveryProof', { occurred_at: '2026-09-03T05:00:00Z' }), n('REPORT', 'RecipientReport', { occurred_at: '2026-09-03T05:30:00Z' }),
      n('SIGN', 'SignatureEvidence'), n('FAR', 'SignatureEvidence'), n('C1', 'CustodyEvent', { occurred_at: '2026-09-01T07:00:00Z' }), n('C0', 'CustodyEvent', { occurred_at: '2026-09-01T05:00:00Z' }),
      n('HUB', 'Hub'), n('DRV', 'Driver'), n('POL', 'Policy'), n('M1', 'ExpectedMilestone', { latest_at: '2026-09-02T00:00:00Z' })],
    edges: [{ id: 'E1', kind: 'HAS_SIGNATURE', start: 'PROOF', end: 'SIGN', properties: {} }, { id: 'E2', kind: 'AT', start: 'C1', end: 'HUB', properties: {} }],
  },
  reasoning: { diagnoses: [{ code: 'DELIVERY_DISPUTE', evidence_ids: ['PROOF', 'REPORT'] }], assessment: { expected_vs_actual: [{ milestone_id: 'M1', late: true }] } },
  recommendation: { evidence_ids: ['PROOF', 'REPORT'] },
  route_layers: { layers: { custody_points: [{ lat: 1, lng: 1, evidence_id: 'C1' }], expected_route: [{ segment_id: 'S', points: [{ lat: 1, lng: 1, entity_id: 'HUB' }] }] } },
}

describe('Evidence categories', () => {
  it('curates key evidence from real citations and their bound components only', () => {
    const { key } = evidenceCategories(detail)
    expect(key.map(k => k.node.id)).toEqual(['PROOF', 'REPORT', 'M1', 'SIGN'])
    expect(key[0].reasons).toEqual([{ kind: 'diagnosis', code: 'DELIVERY_DISPUTE' }, { kind: 'recommendation' }])
    expect(key.find(k => k.node.id === 'SIGN')!.reasons).toEqual([{ kind: 'linked' }])
    expect(key.some(k => k.node.id === 'FAR')).toBe(false)
  })

  it('orders route & custody chronologically and keeps every entity reachable in some category', () => {
    const cats = evidenceCategories(detail)
    expect(cats.route.filter(x => x.kind === 'CustodyEvent').map(x => x.id)).toEqual(['C0', 'C1'])
    expect(cats.parties.map(x => x.id).sort()).toEqual(['DRV', 'HUB'])
    expect(cats.context.map(x => x.id).sort()).toEqual(['POL', 'SHP'])
    const all = new Set([...cats.route, ...cats.parties, ...cats.context].map(x => x.id))
    expect(detail.evidence.nodes.every(x => all.has(x.id))).toBe(true)
  })

  it('offers map navigation only for evidence that is actually plotted', () => {
    expect([...mappedEvidenceIds(detail)].sort()).toEqual(['C1', 'HUB'])
  })
})
