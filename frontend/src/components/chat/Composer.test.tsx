import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { Composer } from './Composer'

describe('Composer send/stop button', () => {
  it('shows Stop (not Send) while busy and calls onStop', () => {
    const onStop = vi.fn()
    render(<Composer onSend={() => {}} busy onStop={onStop} />)
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }))
    expect(onStop).toHaveBeenCalled()
  })

  it('shows a disabled Send when idle with empty input', () => {
    render(<Composer onSend={() => {}} busy={false} />)
    expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true)
    expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull()
  })

  it('sends typed text on click', () => {
    const onSend = vi.fn()
    render(<Composer onSend={onSend} busy={false} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hello' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    expect(onSend).toHaveBeenCalledWith('hello')
  })
})
