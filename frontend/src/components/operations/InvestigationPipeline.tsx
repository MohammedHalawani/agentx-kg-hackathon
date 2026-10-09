import { ArrowUpRight, Check, Hourglass, LoaderCircle, Minus, RotateCcw, X } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { InspectStage, ShipmentDetail } from '@/contracts/caseDetail'
import { stageEvidence } from '@/lib/pipelineEvidence'
import { pipelineSteps, type DisplayStep, type StepStatus } from '@/lib/pipelineSteps'

const REACHED: StepStatus[] = ['COMPLETED', 'RUNNING', 'RETRYING', 'REJECTED', 'HUMAN_REVIEW', 'ESCALATED', 'FAILED', 'UNRECORDED', 'WAITING']

function Glyph({ status }: { status: StepStatus }) {
  const base = 'flex size-7 shrink-0 items-center justify-center rounded-full border text-[13px] font-bold transition-colors duration-200 motion-reduce:transition-none'
  switch (status) {
    case 'COMPLETED': return <span className={`${base} border-chart-good bg-chart-good text-white`}><Check size={14} strokeWidth={3} /></span>
    case 'UNRECORDED': return <span className={`${base} border-chart-good/60 bg-card text-chart-good`}><Check size={14} strokeWidth={2.5} /></span>
    case 'RUNNING': return <span className={`${base} border-primary bg-primary text-primary-foreground ring-2 ring-primary/25`}><LoaderCircle size={14} className="animate-spin motion-reduce:animate-none" /></span>
    case 'RETRYING': return <span className={`${base} border-chart-warning bg-chart-warning text-white ring-2 ring-chart-warning/25`}><RotateCcw size={13} strokeWidth={2.5} /></span>
    case 'REJECTED': return <span className={`${base} border-chart-warning bg-chart-warning text-white`}><X size={14} strokeWidth={3} /></span>
    case 'HUMAN_REVIEW': return <span className={`${base} border-chart-orange bg-chart-orange text-white`} aria-hidden="true">!</span>
    case 'ESCALATED': return <span className={`${base} border-chart-orange bg-chart-orange text-white`}><ArrowUpRight size={14} strokeWidth={2.5} /></span>
    case 'FAILED': return <span className={`${base} border-destructive bg-destructive text-white`}><X size={14} strokeWidth={3} /></span>
    case 'WAITING': return <span className={`${base} border-dashed border-muted-foreground/60 bg-card text-muted-foreground`}><Hourglass size={12} /></span>
    case 'SKIPPED': return <span className={`${base} border-dashed border-border bg-card text-muted-foreground`}><Minus size={12} /></span>
    default: return <span className={`${base} border-border bg-card`} />
  }
}

function StepDetail({ detail, step, onEvidence }: { detail: ShipmentDetail; step: DisplayStep; onEvidence: () => void }) {
  const { t, isArabic, entityLabel, rootCauseLabel } = useLanguage()
  const pipeline = detail.pipeline
  const settled = step.stage === 'outcome' ? undefined
    : pipeline?.events.filter(e => e.stage === step.stage && !['RUNNING', 'RETRYING'].includes(e.status)).at(-1)
  const out = settled?.output
  const ids = stageEvidence(detail, step.stage)
  const loop = pipeline?.events.filter(e => ['recommend', 'review'].includes(e.stage) && !['RUNNING', 'RETRYING'].includes(e.status)) ?? []
  const rejected = pipeline?.events.filter(e => e.status === 'REJECTED').length ?? 0
  const outcomeVerified = detail.outcome?.verification_status === 'VERIFIED' && !detail.outcome.invalidated
  return <div key={step.key} className="space-y-1 rounded-lg bg-muted/40 px-3 py-2 text-xs motion-safe:animate-in motion-safe:fade-in-0 motion-safe:duration-200">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <strong>{t(`ops.pipeline.full.${step.key}`)}</strong>
      <span className="text-muted-foreground">{t(`ops.pipeline.states.${step.status}`)}</span>
      <span>{t('ops.pipeline.relevant', { count: ids.length })}</span>
      {out?.nodes != null && <span>{t('ops.pipeline.retrieved', { nodes: out.nodes, edges: out.relationships ?? 0 })}</span>}
      {out?.verified_precedents != null && <span>{t('ops.pipeline.precedents', { count: out.verified_precedents })}</span>}
      {settled?.recorded_at && <time className="text-[10px] text-muted-foreground" dir="ltr" title={settled.recorded_at} dateTime={settled.recorded_at}>{new Date(settled.recorded_at).toLocaleTimeString('en-GB', { timeZone: 'UTC' })} UTC</time>}
      <button type="button" onClick={onEvidence} className="ms-auto text-primary underline underline-offset-2">{t('ops.pipeline.fullEvidence')}</button>
    </div>
    {step.key === 'collect' && <p className="font-mono" dir="ltr">{detail.shipment_id}</p>}
    {step.key === 'graph' && out?.categories && <p className="text-muted-foreground">{Object.entries(out.categories).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([kind, count]) => `${entityLabel(kind)} ${count}`).join(' · ')}</p>}
    {step.key === 'diagnose' && !!out?.diagnoses?.length && <p>{out.diagnoses.map(d => rootCauseLabel(d.code ?? '')).join(' · ')}</p>}
    {step.key === 'recommend' && out?.proposal && <p dir="auto">{isArabic ? out.proposal.action_ar ?? t('ops.workspace.rejectedGpsProposal') : out.proposal.action_en ?? out.proposal.action}</p>}
    {step.key === 'review' && out?.verdict && <p dir="auto">{t(`ops.review.${out.verdict}`)} · {isArabic ? t(out.verdict === 'accept' ? 'ops.overview.reviewGuard' : 'ops.workspace.gpsGuard') : out.feedback}</p>}
    {step.key === 'route' && out?.workflow_state && <p>{t('ops.pipeline.routedTo', { state: t(`ops.states.${out.workflow_state}`) })} · {t('ops.transition.noSkipToResolved')}</p>}
    {step.key === 'outcome' && <p>{t(detail.decisions?.some(d => d.decision === 'approve') ? 'ops.pipeline.operatorRecorded' : ['AWAITING_APPROVAL', 'HUMAN_REVIEW'].includes(detail.workflow_state ?? '') ? 'ops.pipeline.operatorWaiting' : 'ops.automation.noDecision')} · {t(outcomeVerified ? 'ops.actions.verified' : detail.outcome ? 'ops.actions.observed' : 'ops.pipeline.outcomeWaiting')} · {t('ops.pipeline.outcomeRule')}</p>}
    {['recommend', 'review'].includes(step.key) && rejected > 0 && <details className="pt-1">
      <summary className="cursor-pointer font-medium">{t('ops.pipeline.loop', { count: rejected })}</summary>
      <ol className="mt-1 flex flex-wrap items-center gap-1.5" aria-label={t('ops.pipeline.revision')}>{loop.map((e, i) => <li key={e.sequence} className="flex items-center gap-1.5"><span className={`rounded-md border px-1.5 py-0.5 ${e.status === 'REJECTED' ? 'border-chart-warning/60 bg-chart-warning/10' : 'border-border bg-card'}`}>{t(`ops.pipeline.short.${e.stage === 'recommend' ? 'recommend' : 'review'}`)} {e.stage === 'recommend' ? e.iteration + 1 : e.iteration} · {t(`ops.pipeline.states.${e.status}`)}</span>{i < loop.length - 1 && <span aria-hidden="true" className="text-muted-foreground">{isArabic ? '←' : '→'}</span>}</li>)}</ol>
      <p className="mt-1 text-muted-foreground">{t('ops.workspace.gpsGuard')}</p>
    </details>}
  </div>
}

export function InvestigationPipeline({ detail, selected, onSelect, onEvidence }: { detail: ShipmentDetail; selected: InspectStage; onSelect: (s: InspectStage) => void; onEvidence: () => void }) {
  const { t } = useLanguage()
  const steps = pipelineSteps(detail)
  const current = steps.find(s => s.stage === selected) ?? steps.find(s => s.key === 'diagnose')!
  return <section className="space-y-2 rounded-xl border border-border bg-card p-3" aria-label={t('ops.pipeline.title')}>
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <h3 className="text-sm font-semibold">{t('ops.pipeline.title')}</h3>
      <span className="text-[11px] text-muted-foreground">{t('ops.pipeline.stageMode')}</span>
      {(() => {
        // Live = running now or not started yet; otherwise this is a recorded (completed) run.
        const status = detail.pipeline?.status
        const live = status === 'RUNNING' || (!detail.run && detail.workflow_state && ['OPEN', 'REOPENED', 'INVESTIGATING'].includes(detail.workflow_state))
        return <span data-testid="run-kind" className={`rounded-md border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${live ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
          {live && <span className="me-1 inline-block size-1.5 animate-pulse rounded-full bg-primary align-middle" aria-hidden="true" />}
          {t(live ? 'ops.pipeline.liveRun' : 'ops.pipeline.recordedRun')}
        </span>
      })()}
      <span className="ms-auto text-[11px] text-muted-foreground">{t('ops.automation.inspectOnly')}</span>
    </div>
    <ol className="flex overflow-x-auto pb-1" aria-label={t('ops.pipeline.stages')}>
      {steps.map((step, i) => {
        const reached = REACHED.includes(step.status)
        const gate = step.key === 'outcome'
        const line = (on: boolean, dashed: boolean) => `absolute top-3.5 h-0.5 ${dashed ? 'border-t-2 border-dashed bg-transparent ' + (on ? 'border-chart-good/70' : 'border-border') : on ? 'bg-chart-good/70' : 'bg-border'}`
        const isSelected = current.key === step.key
        return <li key={step.key} className="relative flex min-w-[4.25rem] flex-1 flex-col items-center">
          {i > 0 && <span aria-hidden="true" className={`${line(reached, gate)} start-0 w-1/2`} />}
          {i < steps.length - 1 && <span aria-hidden="true" className={`${line(REACHED.includes(steps[i + 1].status), steps[i + 1].key === 'outcome')} end-0 w-1/2`} />}
          <button type="button" data-stage={step.stage} data-step={step.key} data-stage-status={step.status} aria-pressed={isSelected}
            aria-label={`${t(`ops.pipeline.full.${step.key}`)} · ${t(`ops.pipeline.states.${step.status}`)}${step.revisions ? ` · ${t('ops.pipeline.loop', { count: step.revisions })}` : ''} · ${t('ops.automation.inspect')}`}
            title={`${t(`ops.pipeline.full.${step.key}`)} — ${t(`ops.pipeline.states.${step.status}`)}`}
            onClick={() => onSelect(step.stage)}
            className={`relative z-10 flex flex-col items-center gap-1 rounded-lg px-1.5 pb-1 transition-colors duration-200 motion-reduce:transition-none focus-visible:outline-2 focus-visible:outline-ring ${isSelected ? 'bg-primary/8' : 'hover:bg-muted/60'}`}>
            <span className={`rounded-full transition-shadow duration-200 motion-reduce:transition-none ${isSelected ? 'ring-1 ring-primary/70' : ''}`}><Glyph status={step.status} /></span>
            {step.revisions > 0 && <span aria-hidden="true" className="absolute -top-1 end-0 rounded-full bg-chart-warning px-1 text-[9px] font-semibold leading-4 text-white">↺{step.revisions}</span>}
            <span className={`text-[11px] leading-tight ${isSelected ? 'font-semibold' : 'font-medium'}`}>{t(`ops.pipeline.short.${step.key}`)}</span>
            <span className="text-[9px] leading-tight text-muted-foreground">{t(`ops.pipeline.states.${step.status}`)}</span>
          </button>
        </li>
      })}
    </ol>
    <StepDetail detail={detail} step={current} onEvidence={onEvidence} />
    {!detail.pipeline?.events.length && detail.run && <p className="text-[11px] text-muted-foreground">{t('ops.pipeline.earlier')}</p>}
  </section>
}
