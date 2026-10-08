import { motion, useReducedMotion } from 'motion/react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { CaseWorkflowState } from '@/contracts/operations'
import { CASE_WORKFLOW_VISUAL, workflowAllowsResolvedTransition } from '@/lib/operationalStates'
import { cn } from '@/lib/cn'

const FLOW: CaseWorkflowState[] = [
  'OPEN',
  'INVESTIGATING',
  'RECOMMENDATION_READY',
  'AWAITING_APPROVAL',
  'ACTION_INITIATED',
  'AWAITING_OUTCOME',
  'RESOLVED',
]

export function CaseTransition({ state }: { state: CaseWorkflowState }) {
  const { t } = useLanguage()
  const reduce = useReducedMotion()
  const idx = FLOW.indexOf(state)
  const showResolved = workflowAllowsResolvedTransition(state)

  if (idx < 0) {
    const visual = CASE_WORKFLOW_VISUAL[state]
    return <p role="status" className="rounded-lg border border-border p-2 text-sm">{t(visual.labelKey)}</p>
  }
  return (
    <ol className="flex flex-wrap items-center gap-1 text-[11px]" aria-label={t('ops.transition.label')}>
      {FLOW.map((step, i) => {
        if (step === 'RESOLVED' && !showResolved && state !== 'RESOLVED') return null
        const visual = CASE_WORKFLOW_VISUAL[step]
        const active = step === state
        const done = idx > i
        const blocked =
          step === 'RESOLVED' &&
          state === 'RECOMMENDATION_READY' &&
          !workflowAllowsResolvedTransition(state)
        return (
          <li key={step} className="flex items-center gap-1">
            <motion.span
              layout={!reduce}
              className={cn(
                'rounded-md border px-2 py-0.5',
                active && 'border-primary bg-primary/10 font-medium',
                done && 'border-border text-muted-foreground',
                blocked && 'opacity-40 line-through',
              )}
              title={blocked ? t('ops.transition.noSkipToResolved') : undefined}
            >
              {t(visual.labelKey)}
            </motion.span>
            {i < FLOW.length - 1 && <span className="text-muted-foreground" aria-hidden="true">→</span>}
          </li>
        )
      })}
    </ol>
  )
}
