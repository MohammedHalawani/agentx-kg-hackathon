import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { CaseFile } from '@/types/agent'

export function EvidenceSummary({ caseFile }: { caseFile: CaseFile | null }) {
  const { t } = useLanguage()
  if (!caseFile) {
    return <p className="text-xs text-muted-foreground">{t('ops.evidence.pending')}</p>
  }
  const nodes = caseFile.graph?.nodes.length ?? 0
  const links = caseFile.graph?.relationships.length ?? 0
  const stops = caseFile.route?.points.length ?? 0
  return (
    <dl className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
      <div>
        <dt className="text-muted-foreground">{t('ops.evidence.graph')}</dt>
        <dd className="font-medium tabular-nums" dir="ltr">{nodes} / {links}</dd>
      </div>
      <div>
        <dt className="text-muted-foreground">{t('ops.evidence.route')}</dt>
        <dd className="font-medium tabular-nums" dir="ltr">{stops}</dd>
      </div>
    </dl>
  )
}
