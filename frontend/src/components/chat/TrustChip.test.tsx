import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { TrustChip } from './TrustChip'

// Regression guard: the "grounded" chip must carry real explaining text (it once showed only a help
// cursor with no tooltip), and must render the confidence value.
describe('TrustChip', () => {
  it('shows the grounded label and confidence', () => {
    render(<TrustChip confidence={0.9} />)
    expect(screen.getByText(/grounded · 0\.90/)).toBeTruthy()
  })

  it('exposes, on hover, a tooltip that explains what grounded + the number mean', () => {
    render(<TrustChip confidence={0.86} />)
    expect(screen.queryByRole('tooltip')).toBeNull() // not rendered until hovered
    fireEvent.mouseEnter(screen.getByText(/grounded · 0\.86/).closest('span')!)
    const tip = screen.getByRole('tooltip')
    expect(tip.textContent).toContain('Grounded:')
    expect(tip.textContent).toMatch(/confidence/i)
    expect(tip.textContent).toContain('0.86')
  })
})
