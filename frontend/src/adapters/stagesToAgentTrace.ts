import type { AgentTraceStep } from '@/contracts/operations'
import type { FinalResult, Stage } from '@/types/agent'

const STEP_ORDER: AgentTraceStep['kind'][] = [
  'evidence',
  'similar_cases',
  'hypothesis',
  'recommendation',
  'safety_review',
  'human_decision',
  'outcome',
]

function stepStatus(kind: AgentTraceStep['kind'], stages: Stage[], final: FinalResult | null): AgentTraceStep['status'] {
  const has = (name: Stage['stage']) => stages.some((s) => s.stage === name)
  const last = stages[stages.length - 1]?.stage
  const complete = (k: AgentTraceStep['kind']) => {
    switch (k) {
      case 'evidence':
        return has('extract') || has('retrieve')
      case 'similar_cases':
        return has('retrieve')
      case 'hypothesis':
        return has('classify')
      case 'recommendation':
        return has('recommend')
      case 'safety_review':
        return has('review')
      case 'human_decision':
        return false // Automated safety review does not record a human decision.
      case 'outcome':
        return final?.workflow_state === 'RESOLVED'
      default:
        return false
    }
  }
  if (complete(kind)) return 'complete'
  const activeMap: Partial<Record<AgentTraceStep['kind'], Stage['stage']>> = {
    evidence: 'extract',
    similar_cases: 'retrieve',
    hypothesis: 'classify',
    recommendation: 'recommend',
    safety_review: 'review',
  }
  if (activeMap[kind] === last) return 'active'
  return 'pending'
}

export function stagesToAgentTrace(stages: Stage[], final: FinalResult | null): AgentTraceStep[] {
  return STEP_ORDER.map((kind, index) => ({
    id: `${kind}-${index}`,
    kind,
    titleKey: `ops.trace.${kind}`,
    status: stepStatus(kind, stages, final),
    summary: traceSummary(kind, stages),
  }))
}

function traceSummary(kind: AgentTraceStep['kind'], stages: Stage[]): string | undefined {
  const last = [...stages].reverse().find((s) => {
    const map: Partial<Record<AgentTraceStep['kind'], Stage['stage']>> = {
      evidence: 'extract',
      similar_cases: 'retrieve',
      hypothesis: 'classify',
      recommendation: 'recommend',
      safety_review: 'review',
      human_decision: 'review',
      outcome: 'writeback',
    }
    return s.stage === map[kind]
  })
  if (kind === 'outcome' || kind === 'human_decision') return undefined
  if (!last?.detail) return undefined
  if (kind === 'similar_cases' && last.detail.similar_cases != null) return String(last.detail.similar_cases)
  if (kind === 'hypothesis' && last.detail.category) return last.detail.category
  if (kind === 'recommendation' && last.detail.action) return last.detail.action
  if (kind === 'safety_review' && last.verdict) return last.verdict
  return undefined
}
