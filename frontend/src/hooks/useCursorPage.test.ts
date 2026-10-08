import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { useCursorPage } from './useCursorPage'
describe('Opaque cursor navigation', () => {
  it('returns to the initial page without treating cursors as offsets', () => {
    const { result } = renderHook(useCursorPage)
    act(() => result.current.next('opaque-next', 25))
    expect(result.current.cursor).toBe('opaque-next')
    expect(result.current.hasPrevious).toBe(true)
    act(() => result.current.previous(25))
    expect(result.current.cursor).toBeNull()
    expect(result.current.offset).toBe(0)
    expect(result.current.hasPrevious).toBe(false)
  })
})
