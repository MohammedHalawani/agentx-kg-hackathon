import type { PipelineStage, ShipmentDetail } from '@/contracts/caseDetail'

const KINDS: Record<PipelineStage, string[]> = {
  extract: ['Shipment','Package','Customer','Organization','Address','AddressVersion','RecipientReport'],
  retrieve: ['Shipment','Policy','JourneyPlan','ExpectedMilestone','CustodyEvent','VehicleAssignment'],
  classify: ['ExpectedMilestone','ScanEvent','CustodyEvent','WeightObservation','AddressVersion','DeliveryProof','RecipientReport','TrafficObservation','DeliveryAttempt'],
  retrieve_context: ['Policy','ServiceLevel','JourneyPlan'],
  recommend: ['Shipment','Policy','OpsRecommendation'],
  review: ['Policy','OpsRecommendation','OpsReview','RecipientReport','DeliveryProof'],
  writeback: ['OpsCase','OpsRun','OpsRecommendation','OpsDecision','OpsExecution','OpsOutcome'],
  escalate: ['OpsCase','OpsReview','RecipientReport'],
}
export function stageEvidence(detail: ShipmentDetail, stage: PipelineStage): string[] {
  const nodes = [...detail.evidence.nodes,...(detail.ledger_graph?.nodes ?? [])]
  const event = detail.pipeline?.events.filter(e => e.stage === stage && e.output.evidence_ids?.length).at(-1)
  const selected = new Set(event?.output.evidence_ids ?? [])
  if (stage==='writeback') for (const id of detail.outcome?.evidence_ids ?? []) selected.add(id)
  for (const n of nodes) if (KINDS[stage].includes(n.kind)) selected.add(n.id)
  if (['recommend','review','writeback','escalate'].includes(stage)) {
    const locations=new Set(nodes.filter(n=>['DeliveryAttempt','AddressVersion','LocationPin','CustodyEvent','AuthenticationEvidence','HandoffEvidence','PhotoEvidence','SignatureEvidence'].includes(n.kind)).map(n=>n.id))
    // Two bounded hops along actual DTO relationships, never inferred locations.
    const edges=[...detail.evidence.edges,...(detail.ledger_graph?.edges ?? [])]
    for (let hop=0;hop<2;hop++) {
      const current=new Set(selected)
      for (const e of edges) {
        if(current.has(e.start)&&locations.has(e.end))selected.add(e.end)
        if(current.has(e.end)&&locations.has(e.start))selected.add(e.start)
      }
    }
  }
  return nodes.filter(n => selected.has(n.id)).map(n => n.id)
}
