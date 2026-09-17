import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { TooltipProvider } from '../ui/tooltip'
import { TrustChip } from './TrustChip'

function renderChip(confidence: number) {
  return render(
    <TooltipProvider>
      <TrustChip confidence={confidence} />
    </TooltipProvider>,
  )
}

// Regression guard: the "grounded" chip must carry real explaining text (it once showed only a help
// cursor with no tooltip), and must render the confidence value.
describe('TrustChip', () => {
  it('shows the grounded label and confidence', () => {
    renderChip(0.9)
    expect(screen.getByText(/grounded · 0\.90/)).toBeTruthy()
  })

  it('exposes, on hover, a tooltip that explains what grounded + the number mean', () => {
    renderChip(0.86)
    expect(screen.queryByText(/Grounded:/)).toBeNull() // not rendered until hovered
    fireEvent.mouseEnter(screen.getByText(/grounded · 0\.86/).closest('span')!)
    const tip = screen.getByText(/Grounded:/)
    expect(tip.textContent).toContain('Grounded:')
    expect(tip.textContent).toMatch(/confidence/i)
    expect(tip.textContent).toContain('0.86')
  })
})
