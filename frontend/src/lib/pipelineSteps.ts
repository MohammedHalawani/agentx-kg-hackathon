import type { InspectStage, PipelineEvent, ShipmentDetail } from '@/contracts/caseDetail'

/** Compact display steps over the recorded LangGraph stages, plus the separate outcome gate. */
export type StepKey = 'collect' | 'graph' | 'diagnose' | 'precedent' | 'recommend' | 'review' | 'route' | 'outcome'
export type StepStatus = 'COMPLETED' | 'RUNNING' | 'QUEUED' | 'RETRYING' | 'REJECTED' | 'HUMAN_REVIEW' | 'WAITING' | 'ESCALATED' | 'SKIPPED' | 'FAILED' | 'UNRECORDED'
export interface DisplayStep { key: StepKey; stage: InspectStage; status: StepStatus; revisions: number; event?: PipelineEvent }

const GRAPH_STEPS: [StepKey, InspectStage][] = [
  ['collect', 'extract'], ['graph', 'retrieve'], ['diagnose', 'classify'], ['precedent', 'retrieve_context'],
  ['recommend', 'recommend'], ['review', 'review'],
]

function eventStatus(detail: ShipmentDetail, events: PipelineEvent[]): StepStatus {
  const last = events.at(-1)
  if (last) return last.status as StepStatus
  // An earlier run executed every stage but did not persist per-stage timing.
  if (detail.pipeline?.source === 'earlier_run' && detail.run) return 'UNRECORDED'
  return 'QUEUED'
}

function outcomeStatus(detail: ShipmentDetail): StepStatus {
  const outcome = detail.outcome
  if (outcome && !outcome.invalidated && outcome.verification_status === 'VERIFIED') return 'COMPLETED'
  const state = detail.workflow_state
  if (state === 'ESCALATED') return 'ESCALATED'
  if (outcome && !outcome.invalidated) return 'WAITING'
  // The routing step already shows the human gate; the outcome itself is still pending.
  if (state && ['HUMAN_REVIEW', 'AWAITING_APPROVAL', 'ACTION_INITIATED', 'AWAITING_OUTCOME', 'NEEDS_EVIDENCE'].includes(state)) return 'WAITING'
  return 'QUEUED'
}

export function pipelineSteps(detail: ShipmentDetail): DisplayStep[] {
  const events = detail.pipeline?.events ?? []
  const of = (stage: string) => events.filter(e => e.stage === stage)
  const steps: DisplayStep[] = GRAPH_STEPS.map(([key, stage]) => {
    const own = of(stage)
    return { key, stage, status: eventStatus(detail, own), event: own.at(-1),
      revisions: key === 'review' ? own.filter(e => e.status === 'REJECTED').length : 0 }
  })
  // The graph routes through exactly one terminal branch; show whichever actually ran.
  const escalate = of('escalate')
  const routeStage = escalate.length ? 'escalate' : 'writeback'
  const route = of(routeStage)
  let routeStatus = eventStatus(detail, route)
  if (routeStage === 'escalate' && routeStatus === 'COMPLETED') routeStatus = 'ESCALATED'
  const routed = route.at(-1)?.output.workflow_state
  if (routeStatus === 'COMPLETED' && routed === 'HUMAN_REVIEW') routeStatus = 'HUMAN_REVIEW'
  if (routeStatus === 'COMPLETED' && routed === 'ESCALATED') routeStatus = 'ESCALATED'
  steps.push({ key: 'route', stage: routeStage, status: routeStatus, revisions: 0, event: route.at(-1) })
  steps.push({ key: 'outcome', stage: 'outcome', status: outcomeStatus(detail), revisions: 0 })
  return steps
}

/** The stage the operator should see by default: whatever is executing now, else the diagnosis. */
export function activeStage(detail: ShipmentDetail | null | undefined): InspectStage {
  const latest = detail?.pipeline?.events.at(-1)
  return latest && ['RUNNING', 'RETRYING'].includes(latest.status) ? latest.stage : 'classify'
}

/** Reference and divergence stages are mostly spatial; policy, review, routing and outcome live in the graph. */
export function suggestedFocus(stage: InspectStage): 'map' | 'graph' {
  return ['extract', 'classify'].includes(stage) ? 'map' : 'graph'
}
