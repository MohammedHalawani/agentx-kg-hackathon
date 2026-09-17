import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { CheckCircle2, Inbox, Repeat, Search, TrendingUp, UserCheck } from 'lucide-react'
import { useFetch } from '../../hooks/useFetch'
import type { CasesOverview, EscalatedCase } from '../../types/agent'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { SegmentedProgress } from '@/components/ui/progress'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

type Selection = { kind: 'category'; key: string } | { kind: 'action'; key: string }

const PANEL_HEIGHT = 'h-[440px]'
const QUEUE_HEIGHT = 'h-[400px]'
const ESCALATIONS_HEIGHT = 'h-[360px]'

function displayText(value: string | null | undefined, unavailable: string): string {
  if (value == null || value.trim() === '') return '—'
  if (/^\?+$/.test(value.replace(/\s/g, ''))) return unavailable
  return value
}

function KpiCard({
  label: kpiLabel,
  value,
  detail,
  icon,
  tone = 'default',
}: {
  label: string
  value: string | number
  detail: string
  icon: ReactNode
  tone?: 'default' | 'good' | 'warning'
}) {
  const toneClass =
    tone === 'good'
      ? 'text-chart-good bg-chart-good/10'
      : tone === 'warning'
        ? 'text-chart-warning bg-chart-warning/15'
        : 'text-primary bg-primary/10'

  return (
    <Card className="gap-0 py-0 shadow-none">
      <CardContent className="flex min-h-[92px] items-center gap-3 px-4 py-3">
        <div className={cn('grid size-8 shrink-0 place-items-center rounded-md', toneClass)}>
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-xs font-medium text-muted-foreground">{kpiLabel}</p>
          <p className="text-xl font-semibold leading-tight tabular-nums text-foreground">{value}</p>
          <p className="truncate text-xs text-muted-foreground">{detail}</p>
        </div>
      </CardContent>
    </Card>
  )
}

function CaseCoverageCard({ resolved, open }: { resolved: number; open: number }) {
  const { t } = useLanguage()
  const total = resolved + open
  const pct = total ? Math.round((resolved / total) * 100) : 0

  return (
    <Card className="flex min-h-[120px] flex-col justify-between gap-0 py-0 shadow-none">
      <CardContent className="flex h-full flex-col justify-between px-4 py-3">
        <div>
          <CardTitle className="text-sm font-medium">{t('decisions.coverage.title')}</CardTitle>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums leading-none text-foreground">
              {pct}%
            </span>
            <CardDescription className="text-xs">{t('decisions.coverage.subtitle')}</CardDescription>
          </div>
        </div>
        <div>
          <SegmentedProgress
            className="h-1.5"
            trackClassName="h-1.5"
            segments={[
              { value: resolved, variant: 'success' },
              { value: open, variant: 'pending' },
            ]}
          />
          <div className="mt-2 flex justify-between text-xs text-muted-foreground">
            <span>
              <span className="font-medium tabular-nums text-foreground">{resolved}</span>{' '}
              {t('decisions.coverage.resolved')}
            </span>
            <span>
              <span className="font-medium tabular-nums text-foreground">{open}</span>{' '}
              {t('decisions.coverage.open')}
            </span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function ClosedLoopLearningCard({
  byAgent,
  seeded,
  pending,
}: {
  byAgent: number
  seeded: number
  pending: number
}) {
  const { t } = useLanguage()

  return (
    <Card className="flex min-h-[120px] flex-col justify-between gap-0 py-0 shadow-none">
      <CardContent className="flex h-full flex-col justify-between px-4 py-3">
        <div>
          <CardTitle className="text-sm font-medium">{t('decisions.learning.title')}</CardTitle>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-3xl font-semibold tabular-nums leading-none text-foreground">
              {byAgent}
            </span>
            <CardDescription className="text-xs">{t('decisions.learning.subtitle')}</CardDescription>
          </div>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">
            {t('decisions.learning.seeded', { count: seeded })}
            {pending > 0 && (
              <span className="text-outcome-pending">
                {' · '}
                {t('common.pending', { count: pending })}
              </span>
            )}
          </p>
          <div className="mt-2">
            {byAgent === 0 ? (
              <Badge variant="secondary" className="text-[11px] font-normal">
                {t('decisions.learning.noWritebacks')}
              </Badge>
            ) : (
              <Badge variant="outline" className="border-border text-muted-foreground">
                {t('decisions.learning.badge', { count: byAgent })}
              </Badge>
            )}
            <p className="mt-1.5 text-[11px] text-muted-foreground">{t('decisions.learning.footer')}</p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function MetricRow({
  title,
  meta,
  rate,
  succeeded,
  total,
  selected,
  onSelect,
  dir,
}: {
  title: string
  meta: string
  rate: number
  succeeded: number
  total: number
  selected: boolean
  onSelect: () => void
  dir?: 'auto' | 'ltr'
}) {
  const failed = Math.max(0, total - succeeded)
  const outcomeSegments =
    total > 0
      ? [
          { value: succeeded, variant: 'success' as const },
          ...(failed > 0 ? [{ value: failed, variant: 'failure' as const }] : []),
        ]
      : [{ value: 1, variant: 'neutral' as const }]
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full rounded-md border px-3 py-2.5 text-left transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring',
        selected
          ? 'border-primary/30 bg-accent text-accent-foreground'
          : 'border-transparent hover:border-border hover:bg-muted',
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <Tooltip>
          <TooltipTrigger
            render={
              <span
                dir={dir}
                className={cn(
                  'line-clamp-2 text-xs font-medium leading-snug',
                  selected ? 'text-accent-foreground' : 'text-foreground',
                )}
              >
                {title}
              </span>
            }
          />
          <TooltipContent side="right" className="max-w-xs">
            {title}
          </TooltipContent>
        </Tooltip>
        <span
          className={cn(
            'shrink-0 text-xs font-semibold tabular-nums',
            selected ? 'text-accent-foreground' : 'text-foreground',
          )}
        >
          {Math.round(rate)}%
        </span>
      </div>
      <p className={cn('mt-0.5 text-[11px]', selected ? 'text-accent-foreground/80' : 'text-muted-foreground')}>
        {meta}
      </p>
      <SegmentedProgress segments={outcomeSegments} className="mt-2 h-1" trackClassName="h-1" />
    </button>
  )
}

function ClampedCell({ value, dir }: { value: string; dir?: 'auto' | 'ltr' }) {
  if (value === '—') {
    return (
      <span className="text-muted-foreground" dir={dir}>
        —
      </span>
    )
  }
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span dir={dir} className="line-clamp-2 text-xs leading-snug">
            {value}
          </span>
        }
      />
      <TooltipContent side="top" className="max-w-sm">
        {value}
      </TooltipContent>
    </Tooltip>
  )
}

function EscalationRow({ row, unavailable }: { row: EscalatedCase; unavailable: string }) {
  const { t } = useLanguage()
  const actionsText =
    row.attempted_actions.length > 0
      ? row.attempted_actions.map((a) => displayText(a, unavailable)).join(' · ')
      : '—'

  return (
    <TableRow>
      <TableCell className="text-xs" dir="ltr">
        {row.shipment_id ?? '—'}
      </TableCell>
      <TableCell className="text-xs" dir="auto">
        {displayText(row.team, unavailable)}
      </TableCell>
      <TableCell className="text-xs">{row.priority ?? '—'}</TableCell>
      <TableCell className="max-w-[180px]">
        <ClampedCell value={displayText(row.reason, unavailable)} dir="auto" />
      </TableCell>
      <TableCell className="max-w-[200px]">
        <Tooltip>
          <TooltipTrigger
            render={
              <span dir="auto" className="line-clamp-2 text-xs leading-snug">
                {actionsText}
              </span>
            }
          />
          <TooltipContent side="top" className="max-w-sm">
            <p className="mb-1 font-medium">{displayText(row.complaint, unavailable)}</p>
            <p className="text-muted-foreground">{actionsText}</p>
            {row.complaint && (
              <p className="mt-1 text-[11px] text-muted-foreground">{t('decisions.escalations.alreadyTried')}</p>
            )}
          </TooltipContent>
        </Tooltip>
      </TableCell>
    </TableRow>
  )
}

export function DecisionsView() {
  const { data, loading } = useFetch<CasesOverview>('/cases')
  const { t, rootCauseLabel } = useLanguage()
  const unavailable = t('common.unavailable')

  const categories = useMemo(
    () => (data?.by_category ?? []).filter((c) => !c.category.startsWith('escalation:')),
    [data?.by_category],
  )

  const actions = data?.by_action ?? []
  const [selection, setSelection] = useState<Selection | null>(null)
  const [search, setSearch] = useState('')
  const [rootCauseFilter, setRootCauseFilter] = useState('all')

  useEffect(() => {
    if (!categories.length) return
    setSelection((prev) => prev ?? { kind: 'category', key: categories[0].category })
  }, [categories])

  const queue = data?.queue ?? []

  const uniqueRootCauses = useMemo(
    () => [...new Set(queue.map((c) => c.category))].sort(),
    [queue],
  )

  const filteredQueue = useMemo(() => {
    if (!queue.length) return []
    let items = queue
    if (rootCauseFilter !== 'all') {
      items = items.filter((c) => c.category === rootCauseFilter)
    }
    const q = search.trim().toLowerCase()
    if (q) {
      items = items.filter((c) => {
        const fields = [
          c.failure_id,
          c.shipment_id ?? '',
          rootCauseLabel(c.category),
          c.category,
          displayText(c.city, unavailable),
          displayText(c.courier, unavailable),
        ]
        return fields.some((f) => f.toLowerCase().includes(q))
      })
    }
    return items
  }, [queue, rootCauseFilter, search, rootCauseLabel, unavailable])

  if (loading || !data) {
    return (
      <div className="h-full overflow-y-auto p-4 md:p-6">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[92px] rounded-lg" />
          ))}
        </div>
        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <Skeleton className="h-[120px] rounded-lg" />
          <Skeleton className="h-[120px] rounded-lg" />
        </div>
      </div>
    )
  }

  const { coverage, by_category, writebacks, escalations, escalations_by_team } = data

  const resolvedPct = coverage.total ? Math.round((coverage.resolved / coverage.total) * 100) : 0
  const totalCases = by_category.reduce((a, c) => a + c.cases, 0)
  const totalWon = by_category.reduce((a, c) => a + c.succeeded, 0)
  const overallRate = totalCases ? Math.round((totalWon / totalCases) * 100) : 0
  const openEscalations = escalations.filter((e) => e.status === 'open')

  const selectedCategory =
    selection?.kind === 'category' ? categories.find((c) => c.category === selection.key) : undefined
  const selectedAction =
    selection?.kind === 'action' ? actions.find((a) => a.action === selection.key) : undefined

  const matchingOpenCases =
    selection?.kind === 'category' ? queue.filter((c) => c.category === selection.key) : []

  const panelCardClass = cn(PANEL_HEIGHT, 'min-h-0 flex flex-col gap-0 rounded-lg py-0 shadow-none')

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1600px] space-y-4 p-4 md:p-6">
        <div>
          <h2 className="text-xl font-semibold tracking-tight text-foreground">{t('decisions.title')}</h2>
          <p className="text-sm text-muted-foreground">{t('decisions.subtitle')}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <KpiCard
            label={t('decisions.kpi.openCases')}
            value={coverage.unresolved}
            detail={t('decisions.kpi.openCasesDetail')}
            icon={<Inbox size={15} />}
            tone={coverage.unresolved > 0 ? 'warning' : 'good'}
          />
          <KpiCard
            label={t('decisions.kpi.precedentAvailable')}
            value={coverage.resolved}
            detail={t('decisions.kpi.precedentDetail', { pct: resolvedPct })}
            icon={<CheckCircle2 size={15} />}
            tone={
              coverage.resolved > 0 && coverage.unresolved === 0
                ? 'good'
                : coverage.unresolved > 0
                  ? 'warning'
                  : 'default'
            }
          />
          <KpiCard
            label={t('decisions.kpi.historicalSuccess')}
            value={`${overallRate}%`}
            detail={t('decisions.kpi.historicalDetail', { won: totalWon, total: totalCases })}
            icon={<TrendingUp size={15} />}
          />
          <KpiCard
            label={t('decisions.kpi.waitingHuman')}
            value={openEscalations.length}
            detail={
              escalations.length === 0
                ? t('decisions.kpi.nothingEscalated')
                : t('decisions.kpi.teamsDetail', { count: escalations_by_team.length })
            }
            icon={<UserCheck size={15} />}
            tone={openEscalations.length > 0 ? 'warning' : 'default'}
          />
          <KpiCard
            label={t('decisions.kpi.writtenByAgent')}
            value={writebacks.by_agent}
            detail={
              writebacks.pending > 0
                ? `${t('common.pending', { count: writebacks.pending })} · ${writebacks.by_agent === 0 ? t('decisions.kpi.noAgentResolutions') : t('decisions.kpi.writebackDetail', { total: writebacks.total })}`
                : writebacks.by_agent === 0
                  ? t('decisions.kpi.noAgentResolutions')
                  : t('decisions.kpi.writebackDetail', { total: writebacks.total })
            }
            icon={<Repeat size={15} />}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <CaseCoverageCard resolved={coverage.resolved} open={coverage.unresolved} />
          <ClosedLoopLearningCard
            byAgent={writebacks.by_agent}
            seeded={writebacks.seeded}
            pending={writebacks.pending ?? 0}
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2 xl:grid-cols-[280px_minmax(280px,340px)_1fr]">
          <Card className={panelCardClass}>
            <CardHeader className="shrink-0 border-b px-4 py-2.5">
              <CardTitle className="text-sm">{t('decisions.problems.title')}</CardTitle>
              <CardDescription>{t('decisions.problems.subtitle')}</CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-hidden p-2">
              <ScrollArea className="h-full pr-2">
                <div className="space-y-1">
                  {categories.map((c) => (
                    <MetricRow
                      key={c.category}
                      title={rootCauseLabel(c.category)}
                      meta={t('decisions.workedMeta', { succeeded: c.succeeded, total: c.cases })}
                      rate={c.success_rate}
                      succeeded={c.succeeded}
                      total={c.cases}
                      selected={selection?.kind === 'category' && selection.key === c.category}
                      onSelect={() => setSelection({ kind: 'category', key: c.category })}
                    />
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          <Card className={panelCardClass}>
            <CardHeader className="shrink-0 border-b px-4 py-2.5">
              <CardTitle className="text-sm">{t('decisions.actions.title')}</CardTitle>
              <CardDescription>{t('decisions.actions.subtitle')}</CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-hidden p-2">
              <ScrollArea className="h-full pr-2">
                <div className="space-y-1">
                  {actions.map((a) => (
                    <MetricRow
                      key={a.action}
                      title={displayText(a.action, unavailable)}
                      meta={t('decisions.actions.usedMeta', { used: a.used, succeeded: a.succeeded })}
                      rate={a.success_rate}
                      succeeded={a.succeeded}
                      total={a.used}
                      selected={selection?.kind === 'action' && selection.key === a.action}
                      onSelect={() => setSelection({ kind: 'action', key: a.action })}
                      dir="auto"
                    />
                  ))}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          <Card className={cn(panelCardClass, 'lg:col-span-2 xl:col-span-1')}>
            <CardHeader className="shrink-0 border-b px-4 py-2.5">
              <CardTitle className="text-sm">{t('decisions.focus.title')}</CardTitle>
              <CardDescription>{t('decisions.focus.subtitle')}</CardDescription>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-hidden px-4 py-0">
              <ScrollArea className="h-full py-3">
                {selectedCategory && selection?.kind === 'category' && (
                  <div className="space-y-3 pr-2">
                    <div>
                      <p className="text-xs text-muted-foreground">{t('decisions.focus.rootCause')}</p>
                      <p className="text-sm font-medium text-foreground">
                        {rootCauseLabel(selectedCategory.category)}
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.historicalSuccess')}</p>
                        <p className="font-semibold tabular-nums text-foreground">
                          {Math.round(selectedCategory.success_rate)}%
                        </p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.worked')}</p>
                        <p className="font-semibold tabular-nums text-foreground">
                          {selectedCategory.succeeded} / {selectedCategory.cases}
                        </p>
                      </div>
                      <div className="col-span-2">
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.openCasesNow')}</p>
                        <p className="font-semibold tabular-nums text-foreground">{matchingOpenCases.length}</p>
                      </div>
                    </div>
                    {matchingOpenCases.length > 0 && (
                      <>
                        <Separator />
                        <div>
                          <p className="mb-2 text-xs font-medium text-muted-foreground">
                            {t('decisions.focus.matchingOpenCases')}
                          </p>
                          <Table bare>
                            <TableHeader className="sticky top-0 z-10 bg-card">
                              <TableRow className="hover:bg-transparent">
                                <TableHead className="h-8 bg-card px-1 text-[11px]">{t('table.shipment')}</TableHead>
                                <TableHead className="h-8 bg-card px-1 text-[11px]">{t('table.city')}</TableHead>
                                <TableHead className="h-8 bg-card px-1 text-[11px]">{t('table.courier')}</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {matchingOpenCases.map((c) => (
                                <TableRow key={c.failure_id} className="hover:bg-muted/50">
                                  <TableCell className="px-1 py-1.5 text-xs font-medium" dir="ltr">
                                    {c.shipment_id ?? '—'}
                                  </TableCell>
                                  <TableCell className="px-1 py-1.5 text-xs" dir="auto">
                                    {displayText(c.city, unavailable)}
                                  </TableCell>
                                  <TableCell className="px-1 py-1.5 text-xs" dir="auto">
                                    {displayText(c.courier, unavailable)}
                                  </TableCell>
                                </TableRow>
                              ))}
                            </TableBody>
                          </Table>
                        </div>
                      </>
                    )}
                  </div>
                )}

                {selectedAction && selection?.kind === 'action' && (
                  <div className="space-y-3 pr-2">
                    <div>
                      <p className="text-xs text-muted-foreground">{t('decisions.focus.action')}</p>
                      <p className="text-sm font-medium leading-snug text-foreground" dir="auto">
                        {displayText(selectedAction.action, unavailable)}
                      </p>
                    </div>
                    <div className="grid grid-cols-2 gap-3 text-sm">
                      <div>
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.historicalUses')}</p>
                        <p className="font-semibold tabular-nums text-foreground">{selectedAction.used}</p>
                      </div>
                      <div>
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.succeeded')}</p>
                        <p className="font-semibold tabular-nums text-foreground">{selectedAction.succeeded}</p>
                      </div>
                      <div className="col-span-2">
                        <p className="text-xs text-muted-foreground">{t('decisions.focus.successRate')}</p>
                        <p className="font-semibold tabular-nums text-foreground">
                          {Math.round(selectedAction.success_rate)}%
                        </p>
                      </div>
                    </div>
                  </div>
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        <Card className={cn(QUEUE_HEIGHT, 'flex flex-col gap-0 py-0 shadow-none')}>
          <CardHeader className="shrink-0 border-b px-4 py-3">
            <CardTitle className="text-sm">{t('decisions.queue.titleCount', { count: queue.length })}</CardTitle>
            <CardDescription>{t('decisions.queue.subtitle')}</CardDescription>
          </CardHeader>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-4 py-2">
            <div className="relative min-w-[180px] flex-1">
              <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('decisions.queue.searchPlaceholder')}
                className="h-8 pl-8 text-xs"
              />
            </div>
            <select
              value={rootCauseFilter}
              onChange={(e) => setRootCauseFilter(e.target.value)}
              className="h-8 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="all">{t('common.allRootCauses')}</option>
              {uniqueRootCauses.map((rc) => (
                <option key={rc} value={rc}>
                  {rootCauseLabel(rc)}
                </option>
              ))}
            </select>
          </div>
          <CardContent className="min-h-0 flex-1 overflow-hidden p-0">
            <div className="h-full overflow-auto">
              {filteredQueue.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  {t('common.noResults')}
                </div>
              ) : (
                <Table bare>
                  <TableHeader className="sticky top-0 z-10 bg-card">
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="h-9 bg-card text-xs">{t('table.failureId')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.shipment')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.rootCause')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.city')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.courier')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredQueue.map((c) => {
                      const isSelected =
                        selection?.kind === 'category' && selection.key === c.category
                      return (
                        <TableRow
                          key={c.failure_id}
                          data-state={isSelected ? 'selected' : undefined}
                          className="cursor-pointer"
                          onClick={() => setSelection({ kind: 'category', key: c.category })}
                        >
                          <TableCell className="font-mono text-[11px] text-muted-foreground">
                            {c.failure_id}
                          </TableCell>
                          <TableCell className="text-xs" dir="ltr">
                            {c.shipment_id ?? '—'}
                          </TableCell>
                          <TableCell className="text-xs">
                            {rootCauseLabel(c.category)}
                          </TableCell>
                          <TableCell className="text-xs" dir="auto">
                            {displayText(c.city, unavailable)}
                          </TableCell>
                          <TableCell className="text-xs" dir="auto">
                            {displayText(c.courier, unavailable)}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </div>
          </CardContent>
        </Card>

        <Card
          className={cn(
            'flex flex-col gap-0 py-0 shadow-none',
            escalations.length > 0 ? ESCALATIONS_HEIGHT : 'min-h-0',
          )}
        >
          <CardHeader className="shrink-0 border-b px-4 py-3">
            <CardTitle className="text-sm">
              {escalations.length === 0
                ? t('decisions.escalations.title')
                : t('decisions.escalations.titleOpen', { count: openEscalations.length })}
            </CardTitle>
            <CardDescription>{t('decisions.escalations.subtitle')}</CardDescription>
          </CardHeader>
          <CardContent className={cn('p-0', escalations.length === 0 && 'px-4 py-4')}>
            {escalations.length === 0 ? (
              <Empty className="min-h-[120px] border border-dashed border-border py-6">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <UserCheck />
                  </EmptyMedia>
                  <EmptyTitle>{t('decisions.escalations.emptyTitle')}</EmptyTitle>
                  <EmptyDescription>{t('decisions.escalations.emptyDescription')}</EmptyDescription>
                </EmptyHeader>
              </Empty>
            ) : (
              <div className="h-[280px] overflow-auto">
                <Table bare>
                  <TableHeader className="sticky top-0 z-10 bg-card">
                    <TableRow className="hover:bg-transparent">
                      <TableHead className="h-9 bg-card text-xs">{t('table.shipment')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.team')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.priority')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.reason')}</TableHead>
                      <TableHead className="h-9 bg-card text-xs">{t('table.actions')}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {escalations.map((e) => (
                      <EscalationRow key={e.escalation_id} row={e} unavailable={unavailable} />
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
