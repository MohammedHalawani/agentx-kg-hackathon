import { useState } from 'react'
import { Clock, Loader2, RotateCcw } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/Dialog'
import type { OperationsStatus } from '@/hooks/useQueueSimulation'

/**
 * The scenario world: its clock, whether cases come from the live monitor or from pre-recorded
 * scenario cases, and the explicit operator control to begin a fresh live session.
 */
export function LiveSessionBar({ status, running, pending, onToggle, onReset }: {
  status: OperationsStatus | null
  running: boolean
  pending: boolean
  onToggle?: () => void
  onReset?: () => Promise<void>
}) {
  const { t, isArabic } = useLanguage()
  const [confirm, setConfirm] = useState(false)
  const [resetting, setResetting] = useState(false)
  const session = status?.session
  const live = session?.case_source === 'monitor'
  const clock = status?.as_of ? new Date(status.as_of).toLocaleString(isArabic ? 'ar-SA-u-ca-gregory' : 'en-GB', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—'
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl border border-border bg-card px-3 py-2 text-xs" data-testid="live-session">
      <span className={`rounded-md border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${live ? 'border-primary/50 bg-primary/10 text-primary' : 'border-border text-muted-foreground'}`}>
        {t(live ? 'ops.session.live' : 'ops.session.recorded')}
      </span>
      <span className="text-[10px] font-medium uppercase tracking-wide text-chart-warning">{t('ops.simulation.label')}</span>
      <span className="inline-flex items-center gap-1"><Clock size={12} aria-hidden="true" />{t('ops.session.clock')} <time dir="ltr" className="font-medium tabular-nums">{clock}</time></span>
      {live && <span className="text-muted-foreground">{t('ops.session.monitor', { checked: String(session?.monitor_checked ?? 0), opened: String(session?.monitor_opened ?? 0) })}</span>}
      <span className="text-muted-foreground">{t(live ? 'ops.session.liveHint' : 'ops.session.recordedHint')}</span>
      {onToggle && onReset ? <span className="ms-auto flex gap-1.5">
        <Button size="sm" variant={running ? 'outline' : 'default'} disabled={pending || !status} onClick={onToggle}>
          {pending && <Loader2 className="animate-spin" aria-hidden="true" />}{t(running ? 'ops.session.pause' : 'ops.session.start')}
        </Button>
        <Button size="sm" variant="outline" disabled={!status || resetting} onClick={() => setConfirm(true)}><RotateCcw aria-hidden="true" />{t('ops.session.new')}</Button>
      </span> : <span className="ms-auto text-[11px] text-muted-foreground">{t(running ? 'ops.session.worldRunning' : 'ops.session.worldPaused')}</span>}
      {onReset && <Dialog open={confirm} onOpenChange={setConfirm} title={t('ops.session.confirmTitle')}>
        <p className="text-sm text-muted-foreground">{t('ops.session.confirmBody')}</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" onClick={() => setConfirm(false)}>{t('ops.session.cancel')}</Button>
          <Button disabled={resetting} onClick={async () => { setResetting(true); try { await onReset() } finally { setResetting(false); setConfirm(false) } }}>
            {resetting && <Loader2 className="animate-spin" aria-hidden="true" />}{t('ops.session.confirm')}
          </Button>
        </div>
      </Dialog>}
    </div>
  )
}
