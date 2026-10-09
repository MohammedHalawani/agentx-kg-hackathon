import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { useMemo, useState } from 'react'
import type { AuditEvent } from '@/contracts/operations'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/cn'

function formatTs(iso: string): string {
  try {
    const d = new Date(iso)
    if (!Number.isFinite(d.getTime())) return iso
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'medium' })
  } catch {
    return iso
  }
}

export function AuditLedgerTable({
  events,
  onOpenCase,
  refreshing,
}: {
  events: AuditEvent[]
  onOpenCase?: (shipmentId: string, caseId: string) => void
  refreshing?: boolean
}) {
  const { t, isArabic } = useLanguage()
  const [detail, setDetail] = useState<AuditEvent | null>(null)

  const columns = useMemo<ColumnDef<AuditEvent>[]>(
    () => [
      {
        id: 'time',
        header: () => t('ops.audit.columns.time'),
        cell: ({ row }) => (
          <time className="text-xs tabular-nums text-muted-foreground" dir="ltr" dateTime={row.original.timestamp}>
            {formatTs(row.original.timestamp)}
          </time>
        ),
      },
      {
        id: 'event',
        header: () => t('ops.audit.eventType'),
        cell: ({ row }) => {
          const e = row.original
          const label = e.stage
            ? `${t(`ops.pipeline.stagesNames.${e.stage}`)} · ${t(`ops.pipeline.states.${e.stageStatus}`)}`
            : t(`ops.audit.events.${e.eventType}`)
          return <span className="text-xs font-medium">{label}</span>
        },
      },
      {
        id: 'shipment',
        header: () => t('ops.audit.shipment_id'),
        cell: ({ row }) => <span className="font-mono text-xs" dir="ltr">{row.original.shipmentId}</span>,
      },
      {
        id: 'case',
        header: () => t('ops.audit.case_id'),
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground" dir="ltr">{row.original.caseId ?? '—'}</span>
        ),
      },
      {
        id: 'actor',
        header: () => t('ops.audit.actor'),
        cell: ({ row }) => <span className="text-xs">{row.original.actor}</span>,
      },
      {
        id: 'detail',
        header: () => t('ops.audit.columns.detail'),
        cell: ({ row }) => (
          <Button type="button" variant="ghost" size="xs" onClick={(e) => { e.stopPropagation(); setDetail(row.original) }}>
            {t('ops.audit.detail')}
          </Button>
        ),
      },
    ],
    [t],
  )

  const table = useReactTable({
    data: events,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.id,
    manualPagination: true,
  })

  return (
    <>
      <div className={cn('relative rounded-xl border border-border', refreshing && 'opacity-90')}>
        {refreshing && <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-0.5 animate-pulse bg-primary/40" aria-hidden="true" />}
        <Table dir={isArabic ? 'rtl' : 'ltr'}>
          <TableHeader className="sticky top-0 z-[1] bg-card">
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id}>
                {hg.headers.map((header) => (
                  <TableHead key={header.id} className="whitespace-nowrap text-xs">
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.map((row) => (
              <TableRow
                key={row.id}
                className="cursor-pointer hover:bg-muted/40"
                onClick={() => setDetail(row.original)}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id} className="py-2 align-middle">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <Sheet open={detail != null} onOpenChange={(open) => !open && setDetail(null)}>
        <SheetContent side={isArabic ? 'left' : 'right'} className="w-full max-w-md overflow-y-auto">
          {detail && (
            <>
              <SheetHeader>
                <SheetTitle>{t('ops.audit.detail')}</SheetTitle>
              </SheetHeader>
              <dl className="mt-4 space-y-3 text-sm">
                <div><dt className="text-xs text-muted-foreground">{t('ops.audit.columns.time')}</dt><dd dir="ltr">{formatTs(detail.timestamp)}</dd></div>
                <div><dt className="text-xs text-muted-foreground">{t('ops.audit.shipment_id')}</dt><dd className="font-mono" dir="ltr">{detail.shipmentId}</dd></div>
                {detail.caseId && <div><dt className="text-xs text-muted-foreground">{t('ops.audit.case_id')}</dt><dd className="font-mono" dir="ltr">{detail.caseId}</dd></div>}
                <div><dt className="text-xs text-muted-foreground">{t('ops.audit.actor')}</dt><dd>{detail.actor}{detail.model ? ` · ${detail.model}` : ''}</dd></div>
                {detail.decision && (
                  <div>
                    <dt className="text-xs text-muted-foreground">{t('ops.automation.humanDecision')}</dt>
                    <dd>{t(`ops.actions.${detail.decision}`) === `ops.actions.${detail.decision}` ? detail.decision : t(`ops.actions.${detail.decision}`)}</dd>
                  </div>
                )}
                {detail.result && (
                  <div>
                    <dt className="text-xs text-muted-foreground">{t('ops.audit.columns.recorded')}</dt>
                    <dd className="text-xs text-muted-foreground" dir="auto">{detail.result}</dd>
                  </div>
                )}
              </dl>
              {detail.caseId && onOpenCase && (
                <Button className="mt-4 w-full" onClick={() => { onOpenCase(detail.shipmentId, detail.caseId!); setDetail(null) }}>
                  {t('explore.openCase')}
                </Button>
              )}
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  )
}
