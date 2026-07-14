import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Donut } from './Donut'

const DATA = [
  { label: 'Sold', value: 30 },
  { label: 'Available', value: 70 },
]

// Regression guard: before this, hovering an arc or a legend row showed nothing - only the
// permanently-visible total and each row's percentage, never a segment's exact value.
describe('Donut hover', () => {
  it('shows the dataset total by default', () => {
    render(<Donut data={DATA} unit="units" />)
    expect(screen.getByText('100')).toBeTruthy()
    expect(screen.getByText('units')).toBeTruthy()
  })

  it('swaps the center label to the hovered segment\'s exact value', () => {
    const { container } = render(<Donut data={DATA} unit="units" />)
    const arcs = container.querySelectorAll('g[transform] circle[stroke-dasharray]')
    fireEvent.mouseEnter(arcs[0])
    const centerValue = container.querySelector('svg text')
    expect(centerValue?.textContent).toBe('30')
  })

  it('hovering a legend row also highlights and swaps the center value', () => {
    const { container } = render(<Donut data={DATA} unit="units" />)
    fireEvent.mouseEnter(screen.getByText('Available').closest('li')!)
    const centerValue = container.querySelector('svg text')
    expect(centerValue?.textContent).toBe('70')
  })
})
