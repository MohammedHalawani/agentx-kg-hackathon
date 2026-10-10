import { useLanguage } from '@/components/i18n/LanguageProvider'
import { AgentProse } from '@/components/i18n/AgentProse'
import type { OperationsCase } from '@/contracts/operations'

/**
 * What a queue row says about its case. An accepted agent diagnosis is shown as such, in the investigator's own words;
 * without one the row shows what the monitor observed, never a cause (rule triage is not a diagnosis).
 */
export function CaseSummaryText({ row, className }: { row: OperationsCase; className?: string }) {
  const { t } = useLanguage()
  if (row.diagnosisAvailable === false) {
    const symptoms = (row.symptoms ?? []).map((code) => t(`symptoms.${code}`)).join(' · ')
    return <span data-summary-source="monitor" className={className} dir="auto">{symptoms ? t('ops.queue.symptomsOnly', { symptoms }) : t('ops.queue.noDiagnosis')}</span>
  }
  if (row.diagnosisAvailable) {
    return <span data-summary-source="agent_diagnosis" className={className}><span className="font-medium">{t('ops.queue.agentDiagnosis')}:</span> <AgentProse text={row.issueSummary} /></span>
  }
  return <span className={className} dir="auto">{row.issueSummary}</span>
}
