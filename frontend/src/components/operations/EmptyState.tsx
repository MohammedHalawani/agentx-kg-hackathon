import { Inbox } from 'lucide-react'

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-xl border border-hairline bg-panel px-4 py-8 text-center">
      <Inbox size={22} className="mx-auto mb-2 text-muted-foreground" aria-hidden="true" />
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{description}</p>
    </div>
  )
}
