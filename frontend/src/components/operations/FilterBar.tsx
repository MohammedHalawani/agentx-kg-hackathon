import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function FilterBar({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col gap-3 rounded-xl border border-border bg-card p-3 lg:flex-row lg:flex-wrap lg:items-end', className)}>
      {children}
    </div>
  )
}

export function FilterField({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn('flex min-w-[8rem] flex-1 flex-col gap-1 text-xs text-muted-foreground', className)}>
      <span>{label}</span>
      {children}
    </label>
  )
}
