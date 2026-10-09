import type { ReactNode } from 'react'
import { useIsMobile } from '@/hooks/use-mobile'

export function ResponsiveDisclosure({title,children,defaultOpen=true}:{title:string;children:ReactNode;defaultOpen?:boolean}) {
  const mobile=useIsMobile()
  return <details open={!mobile&&defaultOpen} className="rounded-xl border border-border bg-card p-3"><summary className="cursor-pointer text-sm font-medium">{title}</summary><div className="mt-3 space-y-3">{children}</div></details>
}
