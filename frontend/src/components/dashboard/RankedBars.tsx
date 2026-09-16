export interface RankedItem {
  key: string
  label: string
  value: number // drives bar length
  detail?: string // secondary text shown next to the label, e.g. "12 of 15 closed"
}

// A single-hue ranked comparison (magnitude, not identity) - sequential color job per the
// dataviz skill, so one series needs no legend: the card title already says what's plotted,
// and each row is direct-labeled by name. Bar itself carries the value on hover/focus.
export function RankedBars({ items, unit = '%' }: { items: RankedItem[]; unit?: string }) {
  const max = Math.max(...items.map((i) => i.value), 1)
  return (
    <div className="space-y-3">
      {items.map((item) => {
        const pct = Math.max((item.value / max) * 100, 3)
        return (
          <div key={item.key} className="group/row">
            <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate text-ink">{item.label}</span>
              {item.detail && <span className="shrink-0 text-muted">{item.detail}</span>}
            </div>
            <div className="relative h-3 w-full rounded bg-surface">
              <div
                tabIndex={0}
                className="relative h-full rounded bg-accent outline-none transition-[filter] group-hover/row:brightness-110 group-focus-within/row:brightness-110"
                style={{ width: `${pct}%` }}
              >
                <div className="pointer-events-none absolute -top-8 left-0 z-10 whitespace-nowrap rounded-md border border-hairline bg-panel px-2 py-1 text-xs text-ink opacity-0 shadow-lg transition-opacity group-hover/row:opacity-100 group-focus-within/row:opacity-100">
                  <span className="font-semibold">{item.value}{unit}</span>
                </div>
              </div>
            </div>
          </div>
        )
      })}
    </div>
  )
}
