import { useState, type ReactNode } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { Loader2 } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { AflDivider, StageCard } from '@/components/agent/StageCard'
import { CaseFile } from '@/components/agent/CaseFile'
import { CaseTransition } from '@/components/operations/CaseTransition'
import { EvidenceSummary } from '@/components/operations/EvidenceSummary'
import { stagesToAgentTrace } from '@/adapters/stagesToAgentTrace'
import type { CaseWorkflowState } from '@/contracts/operations'
import type { CaseFile as CaseFileData, FinalResult, Stage } from '@/types/agent'
import { cn } from '@/lib/cn'

type Section = 'overview' | 'evidence' | 'diagnosis' | 'recommendation' | 'review' | 'map' | 'history'

function renderTrace(stages: Stage[]) {
  const out = []
  for (let i = 0; i < stages.length; i++) {
    const s = stages[i]
    out.push(<StageCard key={`${s.stage}-${s.loop}-${i}`} stage={s} index={i} />)
    const isRejectedReview = s.stage === 'review' && s.verdict === 'reject'
    const nextIsRetry = stages[i + 1] && stages[i + 1].stage === 'classify'
    if (isRejectedReview && nextIsRetry) out.push(<AflDivider key={`afl-${i}`} reason={s.detail?.reason} />)
  }
  return out
}

export function CaseWorkspace({
  workflowState,
  complaint,
  stages,
  final,
  caseFile,
  busy,
  error,
  outcome,
}: {
  workflowState: CaseWorkflowState
  complaint: string | null
  stages: Stage[]
  final: FinalResult | null
  caseFile: CaseFileData | null
  busy: boolean
  error: string | null
  outcome: ReactNode
}) {
  const { t, isArabic } = useLanguage()
  const reduce = useReducedMotion()
  const [section, setSection] = useState<Section>('overview')
  const trace = stagesToAgentTrace(stages, final)
  const tabs: { key: Section; label: string }[] = [
    { key: 'overview', label: t('ops.workspace.overview') },
    { key: 'evidence', label: t('ops.workspace.evidence') },
    { key: 'diagnosis', label: t('ops.workspace.diagnosis') },
    { key: 'recommendation', label: t('ops.workspace.recommendation') },
    { key: 'review', label: t('ops.workspace.review') },
    { key: 'map', label: t('ops.workspace.map') },
    { key: 'history', label: t('ops.workspace.history') },
  ]

  return (
    <div className="mx-auto flex h-full max-w-[1600px] flex-col gap-4 lg:flex-row">
      <div className="min-h-0 flex-1 overflow-y-auto lg:max-w-3xl" dir={isArabic ? 'rtl' : undefined}>
        <CaseTransition state={workflowState} />
        <div className="mt-3 flex flex-wrap gap-1 border-b border-border pb-2" role="group" aria-label={t('ops.workspace.overview')}>
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              aria-pressed={section === tab.key}
              onClick={() => setSection(tab.key)}
              className={cn(
                'rounded-lg px-2.5 py-1.5 text-xs focus-visible:outline-2 focus-visible:outline-ring',
                section === tab.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {complaint && section === 'overview' && (
          <div className="mt-4 rounded-xl border border-hairline bg-panel p-3">
            <p className="mb-1 text-[11px] font-medium text-muted-foreground">{t('intake.complaint')}</p>
            <p className="text-sm text-ink" dir="auto">{complaint}</p>
          </div>
        )}

        {section === 'overview' && (
          <ol className="mt-4 space-y-2">
            {trace.map((step) => (
              <li key={step.id} className="rounded-lg border border-border px-3 py-2 text-xs">
                <p className="font-medium">{t(step.titleKey)}</p>
                <p className="text-muted-foreground">{step.summary ?? t(`ops.trace.status.${step.status}`)}</p>
              </li>
            ))}
          </ol>
        )}

        {(section === 'diagnosis' || section === 'recommendation' || section === 'review') && (
          <ul className="relative mt-4">{renderTrace(stages)}</ul>
        )}

        {section === 'evidence' && (
          <div className="mt-4 space-y-3">
            <EvidenceSummary caseFile={caseFile} />
            {caseFile && (
              <div className="min-h-[320px]">
                <CaseFile data={caseFile} />
              </div>
            )}
          </div>
        )}

        {section === 'map' && caseFile && (
          <div className="mt-4 min-h-[420px]">
            <CaseFile data={caseFile} />
          </div>
        )}

        {section === 'history' && (
          <p className="mt-4 text-xs text-muted-foreground">{t('ops.workspace.historyPending')}</p>
        )}

        <AnimatePresence>
          {busy && (
            <motion.div initial={reduce ? false : { opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 size={13} className="animate-spin motion-reduce:animate-none" />
              {stages.length === 0 ? t('intake.starting') : t('intake.working')}
            </motion.div>
          )}
        </AnimatePresence>

        {error && (
          <div className="mt-3 rounded-lg border border-danger/40 bg-danger/5 px-3 py-2 text-xs text-danger">{error}</div>
        )}

        {outcome}
      </div>

      {caseFile && section !== 'evidence' && section !== 'map' && (
        <div className="min-h-[320px] flex-1 lg:min-h-0 lg:max-w-[640px]">
          <CaseFile data={caseFile} />
        </div>
      )}
    </div>
  )
}
