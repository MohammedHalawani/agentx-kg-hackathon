import { useState } from 'react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useOperationsControl, type ReplayMode, type SimulationSpeed, type SimulationStatus } from '@/hooks/useQueueSimulation'
import { LiveSessionBar } from '@/components/intake/LiveSessionBar'
import { SimulationPanel } from '@/components/intake/SimulationPanel'
import { LoadingState } from '@/components/operations/LoadingState'
import { ErrorState } from '@/components/operations/ErrorState'

/**
 * Development tooling, kept off the operator's screens: the synthetic world clock, a new live session,
 * replay speed and single steps. Nothing here is production functionality; it drives the synthetic
 * provider feed that the ingestion worker reads.
 */
export function SimulationView() {
  const { t, isArabic } = useLanguage()
  const simulation = useOperationsControl<SimulationStatus>('simulation')
  const [speed, setSpeed] = useState<SimulationSpeed>(1)
  const [replayMode, setReplayMode] = useState<ReplayMode>('timeline')
  const running = simulation.data?.simulator?.state?.toLowerCase() === 'running'
  return (
    <div className="h-full overflow-y-auto px-4 py-4 sm:px-6 sm:py-5">
      <div className="mx-auto max-w-[1200px] space-y-4" dir={isArabic ? 'rtl' : undefined} data-testid="simulation-view">
        <header>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{t('nav.development')}</p>
          <h2 className="font-display text-xl font-bold text-ink">{t('ops.simulationAdmin.title')}</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{t('ops.simulationAdmin.subtitle')}</p>
        </header>
        <LiveSessionBar
          status={simulation.data}
          running={running}
          pending={simulation.pending}
          onToggle={() => void simulation.command(running ? 'pause' : 'start', running ? {} : { speed: 600, replay_mode: 'timeline' })}
          onReset={async () => { await simulation.command('reset', { confirmation: simulation.data?.development_reset?.confirmation }) }}
        />
        {simulation.data && <SimulationPanel
          running={running}
          onRunningChange={(v) => void simulation.command(v ? 'start' : 'pause', v ? { speed, replay_mode: replayMode } : {})}
          speed={running ? simulation.data.simulator.speed : speed}
          onSpeedChange={(v) => { setSpeed(v); if (running) void simulation.command('start', { speed: v, replay_mode: simulation.data?.simulator.replay_mode ?? replayMode }) }}
          replayMode={running ? simulation.data.simulator.replay_mode ?? replayMode : replayMode}
          onReplayModeChange={v => { setReplayMode(v); if (running) void simulation.command('start', { speed: simulation.data?.simulator.speed ?? speed, replay_mode: v }) }}
          events={[]}
          disabled={simulation.pending || !simulation.data || Boolean(simulation.error)}
          eventCount={simulation.data.simulator?.event_count}
          asOf={simulation.data.as_of}
          onStep={() => void simulation.command('tick', { seconds: 60, speed: running ? simulation.data!.simulator.speed : speed, replay_mode: running ? simulation.data!.simulator.replay_mode : replayMode })}
        />}
        {simulation.error && <ErrorState onRetry={simulation.refetch} />}
        {simulation.loading && !simulation.data && <LoadingState label={t('ops.loading')} />}
      </div>
    </div>
  )
}
