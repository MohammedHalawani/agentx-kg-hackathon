import type { ReactNode } from 'react'
import { useIsMobile } from '@/hooks/use-mobile'

export function ResponsiveDisclosure({title,children}:{title:string;children:ReactNode}) {
  const mobile=useIsMobile()
  return <details open={!mobile} className="rounded-xl border border-border bg-card p-3"><summary className="cursor-pointer text-sm font-medium">{title}</summary><div className="mt-3 space-y-3">{children}</div></details>
}
