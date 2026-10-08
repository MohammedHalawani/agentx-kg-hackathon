import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { AuditEvent } from '@/contracts/operations'
import { cn } from '@/lib/cn'

export function Timeline({ events }: { events: AuditEvent[] }) {
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
            {t(`ops.audit.events.${event.eventType}`)}
            <span className="ms-2 font-mono text-xs text-muted-foreground" dir="ltr">{event.shipmentId}</span>
          </p>
          <p className="text-xs text-muted-foreground">
            {event.actor}
            {event.model ? ` · ${event.model}` : ''}
          </p>
          {(event.decision || event.result) && (
            <p className={cn('mt-1 text-xs', event.decision && 'text-foreground')}>
              {event.decision && <span>{event.decision}</span>}
              {event.result && <span className="text-muted-foreground"> — {event.result}</span>}
            </p>
          )}
        </li>
      ))}
    </ol>
  )
}
