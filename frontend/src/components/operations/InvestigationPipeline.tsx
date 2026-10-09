import { CheckCircle2, Circle, LoaderCircle, RotateCcw, ShieldAlert } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { PipelineStage, ShipmentDetail } from '@/contracts/caseDetail'
import { stageEvidence } from '@/lib/pipelineEvidence'

export function InvestigationPipeline({ detail, selected, onSelect, onEvidence }: { detail:ShipmentDetail; selected:PipelineStage; onSelect:(s:PipelineStage)=>void; onEvidence:()=>void }) {
  const { t, isArabic, entityLabel, rootCauseLabel } = useLanguage()
  const pipeline = detail.pipeline
  const stages = pipeline?.topology.nodes ?? []
  const output = pipeline?.events.filter(e => e.stage === selected && !['RUNNING','RETRYING'].includes(e.status)).at(-1)
  const ids = stageEvidence(detail,selected)
  const retries = pipeline?.events.filter(e => e.status === 'REJECTED') ?? []
  return <section className="space-y-1.5 rounded-xl border border-border bg-card p-3" aria-label={t('ops.pipeline.title')}>
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold">{t('ops.pipeline.title')}</h3><span className="text-xs text-muted-foreground">{t('ops.pipeline.stageMode')}</span></div>
    <p className="text-[11px] text-muted-foreground">{t('ops.automation.inspectOnly')}</p>
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 xl:grid-cols-8" role="group" aria-label={t('ops.pipeline.stages')}>
      {stages.map(stage => {
        const last = pipeline?.events.filter(e => e.stage === stage).at(-1)
        const status = last?.status ?? (stage === 'escalate' && pipeline?.status === 'REVIEWED' ? 'SKIPPED' : pipeline?.source === 'earlier_run' && detail.run ? 'UNRECORDED' : 'QUEUED')
        const Icon = status === 'COMPLETED' ? CheckCircle2 : status === 'RUNNING' ? LoaderCircle : status === 'RETRYING' ? RotateCcw : ['REJECTED','FAILED'].includes(status) ? ShieldAlert : Circle
        return <button key={stage} type="button" aria-label={`${t(`ops.pipeline.stagesNames.${stage}`)} · ${t(`ops.pipeline.states.${status}`)} · ${t('ops.automation.inspect')}`} aria-pressed={selected===stage} data-stage={stage} data-stage-status={status} onClick={()=>onSelect(stage)} className={`min-w-0 rounded-lg border p-1.5 text-start focus-visible:outline-2 focus-visible:outline-ring ${selected===stage?'border-primary/50 bg-muted/40':'border-border'}`}><span className="flex items-center gap-1 text-[11px] font-medium"><Icon size={13} className={`shrink-0 ${status==='RUNNING'?'animate-spin motion-reduce:animate-none':''}`} aria-hidden="true" />{t(`ops.pipeline.stagesNames.${stage}`)}</span><span className="mt-0.5 block text-[9px] text-muted-foreground">{t(`ops.pipeline.states.${status}`)}</span></button>
      })}
    </div>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs"><strong>{t(`ops.pipeline.stagesNames.${selected}`)}</strong><span>{t('ops.pipeline.relevant', { count:ids.length })}</span>{output?.output.diagnoses?.slice(0,3).map((d,i)=><span key={i} className="text-muted-foreground">{rootCauseLabel(d.code??'')}</span>)}{output?.output.nodes != null && <span>{t('ops.pipeline.retrieved',{nodes:output.output.nodes,edges:output.output.relationships??0})}</span>}{output?.output.verified_precedents != null && <span>{t('ops.pipeline.precedents',{count:output.output.verified_precedents})}</span>}{output?.recorded_at&&<time className="text-[10px] text-muted-foreground" dir="ltr" title={output.recorded_at} dateTime={output.recorded_at}>{new Date(output.recorded_at).toLocaleTimeString('en-GB',{timeZone:'UTC'})} UTC</time>}<button type="button" onClick={onEvidence} className="ms-auto text-primary underline underline-offset-2">{t('ops.pipeline.fullEvidence')}</button></div>
    {output?.output.categories && <p className="text-xs text-muted-foreground">{Object.entries(output.output.categories).slice(0,8).map(([kind,count])=>`${entityLabel(kind)} ${count}`).join(' · ')}</p>}
    {selected==='extract' && <p className="font-mono text-xs" dir="ltr">{detail.shipment_id}</p>}
    {output?.output.proposal && <p className="text-xs" dir="auto">{isArabic?output.output.proposal.action_ar??t('ops.workspace.rejectedGpsProposal'):output.output.proposal.action_en??output.output.proposal.action}</p>}
    {output?.output.verdict && <p className="text-xs" dir="auto">{t(`ops.review.${output.output.verdict}`)} · {isArabic?t(output.output.verdict==='accept'?'ops.review.accept':'ops.workspace.gpsGuard'):output.output.feedback}</p>}
    {output?.output.workflow_state && <p className="text-xs">{t(`ops.states.${output.output.workflow_state}`)} · {t('ops.transition.noSkipToResolved')}</p>}

    {!!retries.length && <details className="text-xs"><summary className="cursor-pointer font-medium">{t('ops.pipeline.loop',{count:retries.length})}</summary><ol className="mt-2 flex flex-wrap gap-2" aria-label={t('ops.pipeline.revision')} dir={isArabic?'rtl':'ltr'}>{pipeline?.events.filter(e=>['recommend','review'].includes(e.stage)&&!['RUNNING','RETRYING'].includes(e.status)).map(e=><li key={e.sequence} className="rounded-lg border border-border p-2">{t(`ops.pipeline.stagesNames.${e.stage}`)} {e.stage==='recommend'?e.iteration+1:e.iteration} · {t(`ops.pipeline.states.${e.status}`)} <span aria-hidden="true">{isArabic?'←':'→'}</span></li>)}</ol><p className="mt-2 text-muted-foreground">{t('ops.workspace.gpsGuard')}</p></details>}
    {!pipeline?.events.length && detail.run && <p className="text-xs text-muted-foreground">{t('ops.pipeline.earlier')}</p>}
    <p className="text-xs text-muted-foreground">{t('ops.pipeline.gates')}: {t(detail.decisions?.some(d=>d.decision==='approve')?'ops.pipeline.operatorRecorded':['AWAITING_APPROVAL','HUMAN_REVIEW'].includes(detail.workflow_state??'')?'ops.pipeline.operatorWaiting':'ops.automation.noDecision')} · {t(detail.outcome?.verification_status==='VERIFIED'&&!detail.outcome.invalidated?'ops.actions.verified':detail.outcome?'ops.actions.observed':'ops.pipeline.outcomeWaiting')}</p>
  </section>
}
