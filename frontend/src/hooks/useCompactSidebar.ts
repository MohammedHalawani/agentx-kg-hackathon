import { useEffect, useRef } from 'react'
import { useOptionalSidebar } from '@/components/ui/sidebar'

/**
 * Compacts the desktop sidebar to its icon rail while a focused workspace is mounted,
 * then restores whatever the operator had before. Mobile keeps its drawer untouched.
 * The provider's default is not read from storage, so no global preference changes.
 */
export function useCompactSidebar(active = true) {
  const sidebar = useOptionalSidebar()
  // The provider's setOpen changes identity with `open`; read both through a ref so the
  // effect runs only when the workspace mounts, unmounts or toggles `active`.
  const latest = useRef(sidebar)
  latest.current = sidebar
  const available = !!sidebar && !sidebar.isMobile
  useEffect(() => {
    if (!available || !active) return
    const wasOpen = latest.current?.open ?? true
    latest.current?.setOpen(false)
    return () => { if (wasOpen) latest.current?.setOpen(true) }
  }, [available, active])
}
