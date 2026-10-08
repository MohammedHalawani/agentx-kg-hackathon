import { useLanguage } from '@/components/i18n/LanguageProvider'
import type { SimulationSpeed } from '@/hooks/useQueueSimulation'
import type { SimulationEvent } from '@/hooks/useQueueSimulation'
import type { ReplayMode } from '@/hooks/useQueueSimulation'

export function SimulationPanel({
  running,
  onRunningChange,
  speed,
  onSpeedChange,
  events,
  disabled,
  eventCount,
  asOf,
  onStep,
  replayMode,
  onReplayModeChange,
}: {
  running: boolean
  onRunningChange: (v: boolean) => void
  speed: SimulationSpeed
  onSpeedChange: (v: SimulationSpeed) => void
  events: SimulationEvent[]
  disabled?: boolean
  eventCount?: number
  asOf?: string
  onStep?: () => void
  replayMode?: ReplayMode
  onReplayModeChange?: (mode: ReplayMode) => void
}) {
  const { t } = useLanguage()
  return (
    <section className="rounded-xl border border-dashed border-chart-warning/50 bg-chart-warning/5 p-3" aria-label={t('ops.simulation.title')}>
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">{t('ops.simulation.title')}</h3>
          <p className="text-[11px] font-medium uppercase tracking-wide text-chart-warning">{t('ops.simulation.label')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {onReplayModeChange && <label>{t('ops.simulation.replayMode')} <select value={replayMode ?? 'timeline'} disabled={disabled} onChange={e => onReplayModeChange(e.target.value as ReplayMode)} className="rounded-md border border-border bg-card p-1"><option value="timeline">{t('ops.simulation.timeline')}</option><option value="compressed">{t('ops.simulation.compressed')}</option></select></label>}
          <label className="inline-flex items-center gap-1.5">
            <input type="checkbox" disabled={disabled} checked={running} onChange={(e) => onRunningChange(e.target.checked)} />
            {running ? t('ops.simulation.running') : t('ops.simulation.stopped')}
          </label>
          <select
            value={speed}
            disabled={disabled}
            onChange={(e) => onSpeedChange(Number(e.target.value) as SimulationSpeed)}
            aria-label={t('ops.simulation.speed')}
            className="rounded-md border border-border bg-card px-1.5 py-1"
          >
            <option value={1}>1×</option>
            <option value={10}>10×</option>
            <option value={60}>60×</option>
          </select>
        </div>
      </header>
      {onStep && <button type="button" disabled={disabled || running} onClick={onStep} className="mt-2 rounded-lg border border-border px-3 py-1.5 text-xs disabled:opacity-40">{t('ops.simulation.step')}</button>}
      <p className="mt-2 text-xs text-muted-foreground" role="status">{t('ops.simulation.eventCount', { count: eventCount ?? '—' })} · <time dir="ltr">{asOf ?? '—'}</time></p>
      <ul className="mt-3 max-h-40 space-y-1 overflow-y-auto text-xs" role="log" aria-live="polite">
        {events.length === 0 && eventCount === 0 && <li className="text-muted-foreground">{t('ops.simulation.empty')}</li>}
        {events.map((ev) => (
          <li key={ev.id} className="font-mono" dir="ltr">
            {t(`ops.audit.events.${ev.type}`)} · {ev.shipmentId}
          </li>
        ))}
      </ul>
    </section>
  )
}
