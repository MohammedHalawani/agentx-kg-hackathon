import type { EvidenceNode, ShipmentDetail } from '@/contracts/caseDetail'
import type { StepKey } from './pipelineSteps'

export type EvidenceCategory = 'key' | 'route' | 'parties' | 'context' | 'inventory'
export interface KeyReason { kind: 'diagnosis' | 'recommendation' | 'outcome' | 'milestone' | 'linked'; code?: string }
export interface KeyEvidence { node: EvidenceNode; reasons: KeyReason[]; stages: StepKey[] }

const ROUTE = new Set(['CustodyEvent', 'ScanEvent', 'WeightObservation', 'ExpectedMilestone', 'DeliveryAttempt', 'ContactAttempt', 'GPSObservation', 'TrafficObservation', 'DepotReconciliation', 'DeliveryProof', 'AuthenticationEvidence', 'SignatureEvidence', 'PhotoEvidence', 'HandoffEvidence', 'LocationPin', 'RecipientReport', 'StatusEvent', 'VehicleAssignment', 'DeliverySession'])
const PARTIES = new Set(['Customer', 'Organization', 'Driver', 'Vehicle', 'VehicleType', 'Branch', 'Hub', 'SortingCenter', 'DeliveryDepot', 'OrganizationWarehouse', 'FulfillmentWarehouse', 'Address', 'AddressVersion'])
// Components bound to a cited proof/report: what makes the cited evidence inspectable.
const LINKABLE = new Set(['AuthenticationEvidence', 'SignatureEvidence', 'PhotoEvidence', 'HandoffEvidence', 'DeliveryAttempt', 'LocationPin', 'AddressVersion', 'DepotReconciliation'])
// Stages whose recorded evidence ids are case-specific citations, not the whole retrieval.
const CITING_STAGES: [string, StepKey][] = [['classify', 'diagnose'], ['recommend', 'recommend'], ['review', 'review']]

export function evidenceTime(n: EvidenceNode): string | undefined {
  const p = n.properties
  return (p.occurred_at ?? p.latest_at ?? p.valid_from ?? p.start_at ?? p.recorded_at) as string | undefined
}

export function evidenceCategories(detail: ShipmentDetail) {
  const nodes = detail.evidence.nodes
  const byId = new Map(nodes.map(n => [n.id, n]))
  const reasons = new Map<string, KeyReason[]>()
  const add = (id: string, reason: KeyReason) => {
    if (!byId.has(id)) return
    const list = reasons.get(id) ?? []
    if (!list.some(r => r.kind === reason.kind && r.code === reason.code)) list.push(reason)
    reasons.set(id, list)
  }
  for (const d of detail.reasoning?.diagnoses ?? []) for (const id of d.evidence_ids ?? []) add(id, { kind: 'diagnosis', code: d.code ?? d.category })
  for (const id of detail.recommendation?.evidence_ids ?? []) add(id, { kind: 'recommendation' })
  for (const id of detail.outcome?.evidence_ids ?? []) add(id, { kind: 'outcome' })
  const milestones = new Set((detail.reasoning?.assessment?.expected_vs_actual ?? []).filter(m => m.milestone_id && (m.late || m.missing_due)).map(m => m.milestone_id!))
  for (const id of milestones) add(id, { kind: 'milestone' })
  // One real relationship hop from cited evidence to its bound components.
  const cited = new Set(reasons.keys())
  for (const e of detail.evidence.edges) {
    for (const [from, to] of [[e.start, e.end], [e.end, e.start]]) {
      if (cited.has(from) && !cited.has(to) && LINKABLE.has(byId.get(to)?.kind ?? '')) add(to, { kind: 'linked' })
    }
  }
  const stageHits = (id: string) => CITING_STAGES.filter(([stage]) => detail.pipeline?.events.some(ev => ev.stage === stage && ev.output.evidence_ids?.includes(id))).map(([, key]) => key)
  const rank = (r: KeyReason[]) => Math.min(...r.map(x => ['diagnosis', 'recommendation', 'outcome', 'milestone', 'linked'].indexOf(x.kind)))
  const key: KeyEvidence[] = [...reasons.entries()]
    .map(([id, r]) => ({ node: byId.get(id)!, reasons: r, stages: stageHits(id) }))
    .sort((a, b) => rank(a.reasons) - rank(b.reasons) || (evidenceTime(a.node) ?? '').localeCompare(evidenceTime(b.node) ?? ''))
  const route = nodes.filter(n => ROUTE.has(n.kind)).sort((a, b) => (evidenceTime(a) ?? '').localeCompare(evidenceTime(b) ?? ''))
  const parties = nodes.filter(n => PARTIES.has(n.kind))
  const context = nodes.filter(n => !ROUTE.has(n.kind) && !PARTIES.has(n.kind))
  const precedents = (detail.reasoning?.precedents ?? detail.precedents ?? []).length
  return { key, route, parties, context, precedents }
}

/** Evidence ids that actually have a plotted point or segment in the case's route layers. */
export function mappedEvidenceIds(detail: ShipmentDetail): Set<string> {
  const ids = new Set<string>()
  for (const layer of Object.values(detail.route_layers?.layers ?? {})) for (const item of layer ?? []) {
    const points = 'points' in item ? item.points : [item]
    for (const p of points) { if (p.evidence_id) ids.add(p.evidence_id); if (p.entity_id) ids.add(p.entity_id) }
  }
  return ids
}
