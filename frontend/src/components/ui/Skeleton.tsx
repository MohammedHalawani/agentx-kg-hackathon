import { cn } from '../../lib/cn'

// A pulsing placeholder block sized by the caller to match the content it stands in for.
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-md bg-ink/[0.06]', className)} />
}
