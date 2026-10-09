import * as React from 'react'
import { cn } from '@/lib/cn'

type TabsContextValue = {
  value: string
  onValueChange: (value: string) => void
}

const TabsContext = React.createContext<TabsContextValue | null>(null)

function useTabsContext() {
  const ctx = React.useContext(TabsContext)
  if (!ctx) throw new Error('Tabs components must be used within Tabs')
  return ctx
}

function Tabs({
  value,
  onValueChange,
  className,
  children,
  ...props
}: React.ComponentProps<'div'> & TabsContextValue) {
  return (
    <TabsContext.Provider value={{ value, onValueChange }}>
      <div data-slot="tabs" className={cn('flex flex-col gap-2', className)} {...props}>
        {children}
      </div>
    </TabsContext.Provider>
  )
}

function TabsList({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      role="tablist"
      data-slot="tabs-list"
      className={cn('inline-flex flex-wrap gap-0.5 border-b border-border', className)}
      {...props}
    />
  )
}

function TabsTrigger({
  value,
  className,
  children,
  ...props
}: React.ComponentProps<'button'> & { value: string }) {
  const { value: active, onValueChange } = useTabsContext()
  const selected = active === value
  return (
    <button
      type="button"
      role="tab"
      aria-selected={selected}
      data-state={selected ? 'active' : 'inactive'}
      onClick={() => onValueChange(value)}
      className={cn(
        'relative -mb-px rounded-t-md px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring motion-reduce:transition-none',
        selected
          ? 'border-b-2 border-primary text-foreground'
          : 'border-b-2 border-transparent text-muted-foreground hover:text-foreground',
        className,
      )}
      {...props}
    >
      {children}
    </button>
  )
}

function TabsContent({
  value,
  className,
  children,
  ...props
}: React.ComponentProps<'div'> & { value: string }) {
  const { value: active } = useTabsContext()
  if (active !== value) return null
  return (
    <div role="tabpanel" data-slot="tabs-content" className={cn('min-w-0', className)} {...props}>
      {children}
    </div>
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
