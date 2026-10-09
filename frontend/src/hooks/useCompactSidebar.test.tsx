import { render, renderHook, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SidebarProvider, useSidebar } from '@/components/ui/sidebar'
import { useCompactSidebar } from './useCompactSidebar'

function Probe() { const { state } = useSidebar(); return <span data-testid="state">{state}</span> }
function Workspace() { useCompactSidebar(); return null }

describe('Case workspace sidebar', () => {
  it('compacts the expanded sidebar while a case is open and restores it on Back', () => {
    const { rerender } = render(<SidebarProvider defaultOpen><Probe /><Workspace /></SidebarProvider>)
    expect(screen.getByTestId('state').textContent).toBe('collapsed')
    rerender(<SidebarProvider defaultOpen><Probe /></SidebarProvider>)
    expect(screen.getByTestId('state').textContent).toBe('expanded')
  })

  it('keeps an operator-collapsed sidebar collapsed after leaving the case', () => {
    const { rerender } = render(<SidebarProvider defaultOpen={false}><Probe /><Workspace /></SidebarProvider>)
    rerender(<SidebarProvider defaultOpen={false}><Probe /></SidebarProvider>)
    expect(screen.getByTestId('state').textContent).toBe('collapsed')
  })

  it('is inert outside a sidebar provider (isolated components and tests)', () => {
    expect(() => renderHook(() => useCompactSidebar())).not.toThrow()
  })
})
