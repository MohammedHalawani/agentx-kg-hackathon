import { describe, expect, it, vi } from 'vitest'
import { render } from '@testing-library/react'
import { ArtifactCard } from './ArtifactCard'
import type { Artifact } from '../../types/contract'

// A table-only artifact renders TableView (no NVL/leaflet canvas), so the card mounts cleanly in
// jsdom while still installing the wheel listener under test.
const tableArtifact: Artifact = { tool: 'run_cypher', rows: [{ city: 'Makkah', n: 3 }] }

// Regression guard for the zoom fix at the wiring level (vizWheel.test covers only the predicate):
// a plain wheel is swallowed so the chat scrolls; a Ctrl/⌘ wheel passes through so the viz zooms.
describe('ArtifactCard wheel gating', () => {
  it('stops a plain wheel and lets a Ctrl/⌘ wheel through', () => {
    const { container } = render(<ArtifactCard artifact={tableArtifact} />)
    const card = container.firstElementChild as HTMLElement

    const plain = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: false })
    const plainStop = vi.spyOn(plain, 'stopPropagation')
    card.dispatchEvent(plain)
    expect(plainStop).toHaveBeenCalled()

    const zoom = new WheelEvent('wheel', { bubbles: true, cancelable: true, ctrlKey: true })
    const zoomStop = vi.spyOn(zoom, 'stopPropagation')
    card.dispatchEvent(zoom)
    expect(zoomStop).not.toHaveBeenCalled()
  })
})
