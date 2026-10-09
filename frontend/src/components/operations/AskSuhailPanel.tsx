import { useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import type { ShipmentDetail } from '@/contracts/caseDetail'

const ENABLED = import.meta.env.VITE_OPS_ASK_SUHAIL === 'true'

export function AskSuhailPanel({ detail, caseId }: { detail: ShipmentDetail; caseId?: string }) {
  const { t, isArabic, rootCauseLabel } = useLanguage()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (!ENABLED) return null

  const summarize = () => {
    const dx = detail.reasoning?.diagnoses?.[0]
    const action = isArabic
      ? detail.recommendation?.action_ar ?? detail.recommendation?.action
      : detail.recommendation?.action_en ?? detail.recommendation?.action
    const state = detail.workflow_state ? t(`ops.states.${detail.workflow_state}`) : t('ops.workspace.noDiagnosis')
    const cause = dx ? rootCauseLabel(dx.code ?? '') : t('ops.workspace.noDiagnosis')
    return t('ops.askSuhail.readOnlyReply', {
      shipment: detail.shipment_id,
      case: caseId ?? '—',
      state,
      cause,
      action: action ?? t('ops.overview.noAction'),
    })
  }

  const ask = async () => {
    if (!question.trim() || busy) return
    setBusy(true)
    setAnswer(null)
    try {
      // No safe operations endpoint mutates or re-runs the graph; stay read-only on the client.
      await new Promise((r) => setTimeout(r, 450))
      setAnswer(summarize())
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="space-y-2 rounded-xl border border-border bg-card p-3" aria-label={t('ops.askSuhail.title')}>
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-sm font-semibold">{t('ops.askSuhail.title')}</h3>
        <p className="text-[11px] text-muted-foreground">{t('ops.askSuhail.hint')}</p>
      </div>
      <Textarea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder={t('ops.askSuhail.placeholder')}
        rows={3}
        readOnly={busy}
        dir="auto"
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={busy || !question.trim()} onClick={() => void ask()}>
          {busy ? <LoaderCircle className="animate-spin motion-reduce:animate-none" aria-hidden="true" /> : null}
          {t('ops.askSuhail.submit')}
        </Button>
        <p className="text-[10px] text-muted-foreground">{t('ops.askSuhail.unavailable')}</p>
      </div>
      {answer && (
        <p className="rounded-lg bg-muted/50 p-2 text-xs leading-relaxed text-muted-foreground" dir="auto" role="status">
          {answer}
        </p>
      )}
    </section>
  )
}
