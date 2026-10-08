import { ChevronLeft, ChevronRight } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { cn } from '@/lib/cn'

export function CursorPagination({
  total,
  limit,
  cursorStart,
  nextCursor,
  prevCursor,
  onNext,
  onPrev,
  onLimitChange,
  pageSizes = [25, 50, 100],
}: {
  total: number
  limit: number
  cursorStart: number
  nextCursor: string | null
  prevCursor: string | null
  onNext: () => void
  onPrev: () => void
  onLimitChange: (limit: number) => void
  pageSizes?: number[]
}) {
  const { t, isArabic } = useLanguage()
  const from = total === 0 ? 0 : cursorStart + 1
  const to = Math.min(cursorStart + limit, total)
  const PrevIcon = isArabic ? ChevronRight : ChevronLeft
  const NextIcon = isArabic ? ChevronLeft : ChevronRight

  return (
    <nav className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground" aria-label={t('ops.pagination.label')}>
      <p>
        {t('ops.pagination.showing', { from, to, total })}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="inline-flex items-center gap-1.5">
          {t('ops.pagination.pageSize')}
          <select
            value={limit}
            onChange={(e) => onLimitChange(Number(e.target.value))}
            className="rounded-md border border-border bg-card px-1.5 py-1 text-foreground"
            aria-label={t('ops.pagination.pageSize')}
          >
            {pageSizes.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={onPrev}
          disabled={!prevCursor}
          className={cn('inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1.5 disabled:opacity-40')}
        >
          <PrevIcon size={14} aria-hidden="true" />
          {t('ops.pagination.prev')}
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={!nextCursor}
          className={cn('inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1.5 disabled:opacity-40')}
        >
          {t('ops.pagination.next')}
          <NextIcon size={14} aria-hidden="true" />
        </button>
      </div>
    </nav>
  )
}
