import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, PanelRightClose, PanelRightOpen } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { useOperationsPage } from '@/hooks/useOperationsPage'
import { useCursorPage } from '@/hooks/useCursorPage'
import { adaptCase, pageQuery, type ApiCase } from '@/adapters/operationsApi'
import type { OperationsCase } from '@/contracts/operations'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { PriorityBadge } from '@/components/operations/PriorityBadge'

export const ATTENTION_STATES = ['HUMAN_REVIEW', 'AWAITING_APPROVAL', 'NEEDS_EVIDENCE', 'ESCALATED'] as const
type AttentionState = (typeof ATTENTION_STATES)[number]
const LIMIT = 25

function waiting(openedAt: string | null | undefined, asOf: string | undefined) {
  if (!openedAt || !asOf) return null
  const h = Math.max(0, (Date.parse(asOf) - Date.parse(openedAt)) / 3600000)
  return Number.isFinite(h) ? (h < 48 ? `${Math.round(h)}h` : `${Math.round(h / 24)}d`) : null
}

/**
 * Only cases that need a person. Each tab is its own server-paginated slice of the queue; the rail
 * never carries decision controls — those stay beside the evidence in the case workspace.
 */
export function HumanAttentionRail({ counts, refreshKey, onOpen, collapsed, onCollapsedChange }: {
  counts: Record<string, number>
  refreshKey: unknown
  onOpen: (row: OperationsCase) => void
  collapsed: boolean
  onCollapsedChange: (v: boolean) => void
}) {
  const { t } = useLanguage()
  const [tab, setTab] = useState<AttentionState>('HUMAN_REVIEW')
  const pager = useCursorPage()
  const { data, loading, refetch } = useOperationsPage<ApiCase>(`/cases/queue?${pageQuery({ workflow_state: tab, limit: LIMIT, cursor: pager.cursor })}`, !collapsed)
  useEffect(() => { if (!pager.cursor && !collapsed) refetch() }, [refreshKey]) // eslint-disable-line react-hooks/exhaustive-deps
  const total = ATTENTION_STATES.reduce((n, s) => n + (counts[s] ?? 0), 0)

  if (collapsed) {
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center gap-2 rounded-xl border border-border bg-card py-2" aria-label={t('ops.attention.title')}>
        <Button size="icon-sm" variant="ghost" onClick={() => onCollapsedChange(false)} aria-label={t('ops.attention.expand')}><PanelRightOpen className="rtl:-scale-x-100" /></Button>
        <Badge variant="secondary" className="tabular-nums">{total}</Badge>
        <span className="text-[10px] text-muted-foreground [writing-mode:vertical-rl]">{t('ops.attention.title')}</span>
      </aside>
    )
  }
  const items = (data?.items ?? []).map(adaptCase)
  const asOf = data?.metadata?.as_of
  return (
    <aside className="flex w-[340px] shrink-0 flex-col rounded-xl border border-border bg-card" aria-label={t('ops.attention.title')} data-testid="human-attention">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <h3 className="text-sm font-semibold">{t('ops.attention.title')}</h3>
        <Badge variant="secondary" className="tabular-nums">{total}</Badge>
        <Button size="icon-sm" variant="ghost" className="ms-auto" onClick={() => onCollapsedChange(true)} aria-label={t('ops.attention.collapse')}><PanelRightClose className="rtl:-scale-x-100" /></Button>
      </div>
      <p className="px-3 pt-2 text-[11px] text-muted-foreground">{t('ops.automation.queueContinues')}</p>
      <Tabs value={tab} onValueChange={(v) => { setTab(v as AttentionState); pager.reset() }} className="px-2 pt-2">
        <TabsList className="grid w-full grid-cols-4">
          {ATTENTION_STATES.map(s => (
            <TabsTrigger key={s} value={s} className="flex-col gap-0 px-1 text-[11px] leading-tight">
              <span className="truncate">{t(`ops.attention.tabs.${s}`)}</span>
              <span className="tabular-nums text-muted-foreground">{counts[s] ?? 0}</span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
      <p className="px-3 pt-2 text-[11px] text-muted-foreground">{t(`ops.stateHelp.${tab}`)}</p>
      <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto p-2" aria-busy={loading}>
        {loading && !data ? Array.from({ length: 5 }, (_, i) => <li key={i}><Skeleton className="h-14 w-full" /></li>)
          : items.length === 0 ? <li className="p-3 text-xs text-muted-foreground">{t('ops.attention.empty')}</li>
          : items.map(row => (
            <li key={row.caseId}>
              <button type="button" onClick={() => onOpen(row)} className="w-full rounded-lg border border-transparent px-2 py-1.5 text-start transition-colors hover:border-border hover:bg-muted/50">
                <span className="flex items-center gap-2">
                  <span className="font-mono text-xs font-medium" dir="ltr">{row.shipmentId}</span>
                  <PriorityBadge priority={row.priority} />
                  {waiting(row.openedAt, asOf) && <span className="ms-auto text-[11px] tabular-nums text-muted-foreground" dir="ltr">{t('ops.attention.waiting', { time: waiting(row.openedAt, asOf)! })}</span>}
                </span>
                <span className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{row.issueSummary}</span>
              </button>
            </li>
          ))}
      </ul>
      <div className="flex items-center justify-between border-t border-border px-2 py-1.5 text-[11px] text-muted-foreground">
        <span className="tabular-nums" dir="ltr">{data ? `${pager.offset + (items.length ? 1 : 0)}–${pager.offset + items.length} / ${data.filtered_total}` : ''}</span>
        <span className="flex gap-1">
          <Button size="icon-xs" variant="ghost" disabled={!pager.hasPrevious} onClick={() => pager.previous(LIMIT)} aria-label={t('ops.pagination.prev')}><ChevronLeft className="rtl:-scale-x-100" /></Button>
          <Button size="icon-xs" variant="ghost" disabled={!data?.next_cursor} onClick={() => pager.next(data?.next_cursor, LIMIT)} aria-label={t('ops.pagination.next')}><ChevronRight className="rtl:-scale-x-100" /></Button>
        </span>
      </div>
    </aside>
  )
}
