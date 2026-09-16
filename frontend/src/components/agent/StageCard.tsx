import { AnimatePresence, motion } from 'motion/react'
import {
  AlertTriangle,
  ArrowUpRight,
  Check,
  CheckCircle2,
  Database,
  Scale,
  Search,
  Tags,
  Wrench,
  X,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '../../lib/cn'
import type { Stage } from '../../types/agent'

// Icon per pipeline stage, matching the architecture diagram's reading order.
const STAGE_ICON: Record<Stage['stage'], typeof Search> = {
  extract: Search,
  retrieve: Database,
  classify: Tags,
  recommend: Wrench,
  review: Scale,
  writeback: CheckCircle2,
  escalate: ArrowUpRight,
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-2 text-xs">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <span className="min-w-0 flex-1 text-ink">{children}</span>
    </div>
  )
}

// A 0-1 model score as a compact meter. Direct-labelled with the number, so the bar is
// reinforcement rather than the only way to read the value (see the dataviz skill).
function ScoreMeter({ value, tone }: { value: number; tone: 'good' | 'warning' | 'accent' }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100)
  const fill = tone === 'good' ? 'bg-chart-good' : tone === 'warning' ? 'bg-chart-warning' : 'bg-chart-blue'
  return (
    <span className="inline-flex items-center gap-2">
      <span className="h-1.5 w-20 overflow-hidden rounded-full bg-hairline">
        <motion.span
          className={cn('block h-full rounded-full', fill)}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </span>
      <span className="tabular-nums text-ink">{pct}%</span>
    </span>
  )
}

// Renders whatever this particular stage produced. Each branch shows the outputs the
// diagram names for that lane (Category/Confidence+Priority, candidate actions,
// Evaluation Score/Accept-Reject/Reason) rather than a generic key-value dump.
function StageBody({ stage }: { stage: Stage }) {
  const d = stage.detail
  if (!d) return null

  if (stage.stage === 'extract') {
    const entries = (
      [
        ['Shipment', d.shipment_id],
        ['Tracking', d.tracking_id],
        ['City', d.city],
        ['District', d.district],
        ['Courier', d.courier],
        ['Hint', d.category_hint],
      ] as const
    ).filter(([, v]) => Boolean(v))
    if (!entries.length) return <p className="text-xs text-muted">Nothing resolved to a graph entity.</p>
    return (
      <div className="flex flex-wrap gap-1.5">
        {entries.map(([k, v]) => (
          <span key={k} className="rounded-md bg-surface px-2 py-1 text-xs text-ink">
            <span className="text-muted">{k} </span>
            {v}
          </span>
        ))}
      </div>
    )
  }

  if (stage.stage === 'retrieve') {
    return (
      <div className="space-y-2">
        <Field label="Fused">
          {d.similar_cases ?? 0} precedent case{(d.similar_cases ?? 0) === 1 ? '' : 's'} (vector KNN + graph, RRF)
        </Field>
        {d.precedent?.length ? (
          <ul className="space-y-1">
            {d.precedent.map((p) => (
              <li key={p.failure_id} className="flex items-start gap-2 rounded-md bg-surface px-2 py-1.5 text-xs">
                {p.success ? (
                  <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-chart-good" />
                ) : (
                  <AlertTriangle size={12} className="mt-0.5 shrink-0 text-chart-warning" />
                )}
                <span className="min-w-0 flex-1">
                  <span className="text-ink">{p.action}</span>
                  <span className="text-muted">
                    {' '}
                    · {p.category}
                    {p.success ? ' · worked' : ' · did not work'}
                  </span>
                </span>
                <span className="shrink-0 tabular-nums text-muted">{p.score?.toFixed(3)}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    )
  }

  if (stage.stage === 'classify') {
    return (
      <div className="space-y-1.5">
        <Field label="Category">
          <span className="font-medium">{d.category}</span>
        </Field>
        <Field label="Confidence">
          <ScoreMeter value={d.confidence ?? 0} tone="accent" />
        </Field>
        <Field label="Priority">{d.priority}</Field>
        {d.rationale && <Field label="Rationale">{d.rationale}</Field>}
      </div>
    )
  }

  if (stage.stage === 'recommend') {
    return (
      <div className="space-y-1.5">
        <Field label="Action">
          <span className="font-medium" dir="auto">
            {d.action}
          </span>
        </Field>
        {d.grounded_in?.length ? (
          <Field label="Grounded in">
            {d.grounded_in.length} historical resolution{d.grounded_in.length === 1 ? '' : 's'}
          </Field>
        ) : (
          <Field label="Grounded in">
            <span className="text-chart-warning">no precedent — unsupported</span>
          </Field>
        )}
        {d.rationale && <Field label="Rationale">{d.rationale}</Field>}
        {d.candidates?.length ? (
          <div className="pt-1">
            <p className="mb-1 text-xs text-muted">Also considered</p>
            <ul className="space-y-1">
              {d.candidates.slice(0, 3).map((c) => (
                <li key={c.action} className="flex items-center gap-2 text-xs">
                  <span className="min-w-0 flex-1 truncate text-ink" dir="auto">
                    {c.action}
                  </span>
                  {typeof c.success_rate === 'number' && (
                    <span className="shrink-0 tabular-nums text-muted">{Math.round(c.success_rate)}%</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>
    )
  }

  if (stage.stage === 'review') {
    const rejected = d.verdict === 'reject'
    return (
      <div className="space-y-1.5">
        <Field label="Verdict">
          <span className={cn('inline-flex items-center gap-1 font-medium', rejected ? 'text-chart-warning' : 'text-chart-good')}>
            {rejected ? <X size={12} /> : <Check size={12} />}
            {rejected ? 'Reject' : 'Accept'}
          </span>
        </Field>
        <Field label="Score">
          <ScoreMeter value={d.score ?? 0} tone={rejected ? 'warning' : 'good'} />
        </Field>
        {d.reason && <Field label="Reason">{d.reason}</Field>}
        {d.checked_against?.length ? (
          <Field label="Checked">
            <span className="flex flex-wrap gap-1">
              {d.checked_against.map((c) => (
                <span key={c} className="rounded bg-surface px-1.5 py-0.5 text-[11px] text-muted">
                  {c}
                </span>
              ))}
            </span>
          </Field>
        ) : null}
      </div>
    )
  }

  if (stage.stage === 'writeback') {
    return (
      <Field label="Written">
        <span className="text-chart-good">{d.resolution_id}</span> — now retrievable as precedent
      </Field>
    )
  }

  return null
}

// One stage in the vertical trace. The left rail carries the diagram's lane name; the three
// named agents get their Arabic name and an accent ring so they read as decision-makers
// rather than plumbing.
export function StageCard({ stage, index }: { stage: Stage; index: number }) {
  const Icon = STAGE_ICON[stage.stage] ?? Search
  const rejected = stage.verdict === 'reject'

  return (
    <motion.li
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut', delay: Math.min(index * 0.02, 0.1) }}
      className="relative flex gap-3 pl-1"
    >
      <div className="flex w-[104px] shrink-0 flex-col items-end pt-2 text-right">
        <span className="text-[11px] font-medium text-muted">{stage.lane}</span>
        {stage.arabic && (
          <span className="text-xs text-accent" dir="rtl">
            {stage.arabic}
          </span>
        )}
      </div>

      <div className="relative flex flex-col items-center">
        <span
          className={cn(
            'z-10 flex size-7 shrink-0 items-center justify-center rounded-full border',
            stage.is_agent ? 'border-accent bg-accent-soft text-accent' : 'border-hairline bg-panel text-muted',
            rejected && 'border-chart-warning bg-chart-warning/10 text-chart-warning',
          )}
        >
          <Icon size={14} />
        </span>
        <span className="absolute top-7 bottom-0 w-px bg-hairline" aria-hidden />
      </div>

      <div className="min-w-0 flex-1 pb-4">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
          <h4 className="text-sm font-semibold text-ink">{stage.label}</h4>
          {stage.loop > 0 && stage.stage !== 'escalate' && (
            <span className="rounded-full bg-chart-warning/15 px-1.5 py-0.5 text-[10px] font-medium text-chart-warning">
              AFL retry {stage.loop}
            </span>
          )}
        </div>
        <div className="mt-1.5 rounded-lg border border-hairline bg-panel p-2.5">
          <StageBody stage={stage} />
        </div>
      </div>
    </motion.li>
  )
}

// The banner between a rejected review and the re-classification it triggers - the diagram's
// red "AFL — Reject Feedback" edge, drawn where it actually happens in the trace.
export function AflDivider({ reason }: { reason?: string }) {
  return (
    <AnimatePresence>
      <motion.li
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="my-1 ml-[116px] flex items-start gap-2 rounded-lg border border-dashed border-chart-warning/50 bg-chart-warning/5 px-3 py-2"
      >
        <AlertTriangle size={13} className="mt-0.5 shrink-0 text-chart-warning" />
        <p className="text-xs text-ink">
          <span className="font-medium text-chart-warning">AFL feedback loop</span> — the reviewer rejected the
          recommendation, so the root cause is re-classified with that objection in hand.
          {reason && <span className="text-muted"> {reason}</span>}
        </p>
      </motion.li>
    </AnimatePresence>
  )
}
