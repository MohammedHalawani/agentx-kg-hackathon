import { useState } from 'react'
import * as Popover from '@radix-ui/react-popover'
import { Lightbulb } from 'lucide-react'
import type { SampleGroup } from '../../types/contract'

interface ExamplesMenuProps {
  groups: SampleGroup[]
  onPick: (question: string) => void
}

// A compact popover of every sample question, grouped by domain — reachable from the composer at
// any point in the conversation, not just the empty state. Radix handles focus/escape/click-away.
export function ExamplesMenu({ groups, onPick }: ExamplesMenuProps) {
  const [open, setOpen] = useState(false)
  if (!groups.length) return null

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger asChild>
        <button
          type="button"
          aria-label="Example questions"
          className="flex h-8 shrink-0 items-center gap-1.5 rounded-full border border-hairline bg-panel pl-2.5 pr-3 text-xs font-medium text-muted transition-colors hover:border-accent hover:text-ink data-[state=open]:border-accent data-[state=open]:bg-accent-soft data-[state=open]:text-accent"
        >
          <Lightbulb size={15} />
          Examples
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          side="top"
          align="start"
          sideOffset={10}
          className="z-[1200] max-h-[min(60vh,26rem)] w-[min(30rem,88vw)] overflow-y-auto rounded-2xl border border-hairline bg-panel p-2 shadow-2xl"
        >
          <div className="px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">
            Try an example
          </div>
          {groups.map((g) => (
            <div key={g.label} className="mt-1">
              <div className="px-3 py-1 text-[11px] font-medium text-muted/80">{g.label}</div>
              {g.questions.map((q) => (
                <button
                  key={q}
                  onClick={() => {
                    onPick(q)
                    setOpen(false)
                  }}
                  className="block w-full rounded-lg px-3 py-3 text-left text-sm leading-snug text-ink transition-colors hover:bg-accent-soft"
                >
                  {q}
                </button>
              ))}
            </div>
          ))}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
