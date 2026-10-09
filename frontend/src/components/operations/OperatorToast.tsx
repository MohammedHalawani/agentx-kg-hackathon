import { useCallback, useEffect, useState } from 'react'
import { cn } from '@/lib/cn'

type Toast = { id: number; message: string }

let pushToast: ((message: string) => void) | null = null

/** Fire-and-forget operator feedback (not wired to pipeline polling). */
export function notifyOperator(message: string) {
  pushToast?.(message)
}

export function OperatorToastRegion() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])
  useEffect(() => {
    pushToast = (message: string) => {
      const id = Date.now()
      setToasts((prev) => [...prev.slice(-2), { id, message }])
      window.setTimeout(() => dismiss(id), 4200)
    }
    return () => {
      pushToast = null
    }
  }, [dismiss])
  if (!toasts.length) return null
  return (
    <div
      className="pointer-events-none fixed bottom-4 z-[500] flex max-w-sm flex-col gap-2 end-4"
      aria-live="polite"
    >
      {toasts.map((t) => (
        <p
          key={t.id}
          className={cn(
            'pointer-events-auto rounded-lg border border-border bg-card px-3 py-2 text-xs text-foreground shadow-md motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-2 motion-safe:duration-200',
          )}
        >
          {t.message}
        </p>
      ))}
    </div>
  )
}
