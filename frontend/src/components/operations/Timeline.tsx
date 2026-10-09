import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { AuditEvent } from '@/contracts/operations'
import { cn } from '@/lib/cn'

export function Timeline({ events, onOpenCase }: { events: AuditEvent[]; onOpenCase?: (shipmentId: string, caseId: string) => void }) {
  const { t, isArabic } = useLanguage()
  return (
    <ol className="space-y-3" dir={isArabic ? 'rtl' : 'ltr'}>
      {events.map((event) => (
        <li key={event.id} className="relative rounded-lg border border-border bg-card px-3 py-2 text-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <time className="text-xs tabular-nums text-muted-foreground" dir="ltr" dateTime={event.timestamp}>
              {event.timestamp}
            </time>
            {event.fixture && (
              <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                {t('ops.fixture.badge')}
              </span>
            )}
          </div>
          <p className="mt-1 font-medium">
            {event.stage ? `${t(`ops.pipeline.stagesNames.${event.stage}`)} · ${t(`ops.pipeline.states.${event.stageStatus}`)}` : t(`ops.audit.events.${event.eventType}`)}
            <span className="ms-2 font-mono text-xs text-muted-foreground" dir="ltr">{event.shipmentId}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {event.actor}
            {event.model ? ` · ${event.model}` : ''}
          </p>
          {event.caseId && onOpenCase && <button type="button" onClick={() => onOpenCase(event.shipmentId, event.caseId!)} className="mt-2 rounded border border-border px-2 py-1 text-xs">{t('explore.openCase')}</button>}
          {(event.decision || event.result) && (
            <div className={cn('mt-1 text-xs', event.decision && 'text-foreground')}>
              {event.decision && <span>{t(`ops.actions.${event.decision}`) === `ops.actions.${event.decision}` ? event.decision : t(`ops.actions.${event.decision}`)}</span>}
              {event.result && <details className="mt-2 text-muted-foreground"><summary className="cursor-pointer">{t('ops.audit.detail')}</summary><p className="mt-1" dir="auto">{event.result}</p></details>}
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}
