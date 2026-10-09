import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { Copy, EllipsisVertical, ExternalLink, FileSearch, FolderOpen } from 'lucide-react'
import { useMemo } from 'react'
import type { OperationsCase } from '@/contracts/operations'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { CaseWorkflowBadge, OperationalStatusBadge } from './StatusBadge'
import { PriorityBadge } from './PriorityBadge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { humanActionI18nKey, humanActionRequired } from '@/lib/humanAction'
import { cn } from '@/lib/cn'
import { EmptyState } from './EmptyState'

function formatOpened(iso?: string | null): string {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (!Number.isFinite(d.getTime())) return iso
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return iso
  }
}

export type QueueCaseRowActions = {
  onOpen: (row: OperationsCase) => void
  onCopyId: (row: OperationsCase) => void
  onExplore?: (row: OperationsCase) => void
  onAudit?: (row: OperationsCase) => void
}

export function QueueCasesTable({
  cases,
  actions,
  emptyTitle,
  emptyDescription,
  refreshing,
}: {
  cases: OperationsCase[]
  actions: QueueCaseRowActions
  emptyTitle: string
  emptyDescription: string
  refreshing?: boolean
}) {
  const { t, rootCauseLabel, isArabic } = useLanguage()

  const columns = useMemo<ColumnDef<OperationsCase>[]>(
    () => [
      {
        id: 'shipment',
        header: () => t('ops.table.shipment'),
        cell: ({ row }) => (
          <span className="font-mono text-xs" dir="ltr">{row.original.shipmentId}</span>
        ),
      },
      {
        id: 'issue',
        header: () => t('ops.table.issue'),
        cell: ({ row }) => (
          <span className="line-clamp-2 text-sm" dir="auto">
            {row.original.issueSummary || (row.original.category ? rootCauseLabel(row.original.category) : '—')}
          </span>
        ),
      },
      {
        id: 'priority',
        header: () => t('ops.table.priority'),
        cell: ({ row }) => <PriorityBadge priority={row.original.priority} />,
      },
      {
        id: 'workflow',
        header: () => t('ops.filters.workflow'),
        cell: ({ row }) => (
          <Tooltip>
            <TooltipTrigger render={<span className="inline-flex max-w-[10rem]" />}>
              <CaseWorkflowBadge state={row.original.workflowState} />
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">{t('ops.table.workflowHint')}</TooltipContent>
          </Tooltip>
        ),
      },
      {
        id: 'operational',
        header: () => t('ops.filters.operational_status'),
        cell: ({ row }) =>
          row.original.operationalStatus ? (
            <Tooltip>
              <TooltipTrigger render={<span className="inline-flex max-w-[10rem]" />}>
                <OperationalStatusBadge status={row.original.operationalStatus} />
              </TooltipTrigger>
              <TooltipContent className="max-w-xs">{t('ops.table.operationalHint')}</TooltipContent>
            </Tooltip>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          ),
      },
      {
        id: 'city',
        header: () => t('ops.table.city'),
        cell: ({ row }) =>
          row.original.city ? (
            <span className="text-xs" dir="auto">{t(`cities.${row.original.city}`)}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
      {
        id: 'opened',
        header: () => t('ops.table.openedUpdated'),
        cell: ({ row }) => (
          <time className="text-xs tabular-nums text-muted-foreground" dir="ltr" dateTime={row.original.openedAt ?? undefined}>
            {formatOpened(row.original.openedAt)}
          </time>
        ),
      },
      {
        id: 'human',
        header: () => t('ops.table.humanAction'),
        cell: ({ row }) => {
          const i18nKey = humanActionI18nKey(row.original.workflowState)
          if (!i18nKey) return <span className="text-xs text-muted-foreground">—</span>
          return (
            <span
              className={cn(
                'text-xs font-medium',
                humanActionRequired(row.original.workflowState) ? 'text-chart-warning' : 'text-muted-foreground',
              )}
            >
              {t(i18nKey)}
            </span>
          )
        },
      },
      {
        id: 'actions',
        header: () => <span className="sr-only">{t('ops.table.rowActions')}</span>,
        cell: ({ row }) => (
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="ghost" size="icon-sm" className="size-8" onClick={(e) => e.stopPropagation()} aria-label={t('ops.table.rowActions')} />
              }
            >
              <EllipsisVertical size={16} />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuItem onClick={() => actions.onOpen(row.original)}>
                <FolderOpen size={14} /> {t('explore.openCase')}
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => actions.onCopyId(row.original)}>
                <Copy size={14} /> {t('ops.table.copyId')}
              </DropdownMenuItem>
              {actions.onExplore && (
                <DropdownMenuItem onClick={() => actions.onExplore?.(row.original)}>
                  <ExternalLink size={14} /> {t('nav.explore')}
                </DropdownMenuItem>
              )}
              {actions.onAudit && (
                <DropdownMenuItem onClick={() => actions.onAudit?.(row.original)}>
                  <FileSearch size={14} /> {t('nav.audit')}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        ),
      },
    ],
    [t, rootCauseLabel, actions],
  )

  const table = useReactTable({
    data: cases,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.caseId,
    manualPagination: true,
  })

  if (!cases.length) {
    return <EmptyState title={emptyTitle} description={emptyDescription} />
  }

  return (
    <div className={cn('relative rounded-xl border border-border', refreshing && 'opacity-90')}>
      {refreshing && (
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 animate-pulse bg-primary/40" aria-hidden="true" />
      )}
      <Table dir={isArabic ? 'rtl' : 'ltr'}>
        <TableHeader className="sticky top-0 z-[1] bg-card">
          {table.getHeaderGroups().map((hg) => (
            <TableRow key={hg.id}>
              {hg.headers.map((header) => (
                <TableHead key={header.id} className="whitespace-nowrap text-xs">
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow
              key={row.id}
              className="cursor-pointer hover:bg-muted/50"
              onClick={() => actions.onOpen(row.original)}
            >
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id} className="align-middle py-2">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
