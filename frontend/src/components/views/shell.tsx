import type { ReactNode } from 'react'

// A full-height bordered surface the graph/map/schema lenses fill, with rounded chrome.
export function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="h-full p-4">
      <div className="h-full overflow-hidden rounded-2xl border border-hairline">{children}</div>
    </div>
  )
}

export function Center({ children }: { children: ReactNode }) {
  return <div className="grid h-full place-items-center px-6 text-center text-sm text-muted">{children}</div>
}
