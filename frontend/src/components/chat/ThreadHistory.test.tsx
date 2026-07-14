import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { ThreadHistory } from './ThreadHistory'

afterEach(() => vi.unstubAllGlobals())

const open = () => fireEvent.click(screen.getByRole('button', { name: 'Chat history' }))

describe('ThreadHistory', () => {
  it('fetches and lists past conversations on open', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ threads: [{ id: 't1', title: 'First Q', messages: 2 }] }) }),
    )
    render(<ThreadHistory activeThreadId="x" onLoad={() => {}} onNew={() => {}} />)
    open()
    expect(await screen.findByText('First Q')).toBeTruthy()
    expect(screen.getByText(/2 messages/)).toBeTruthy()
  })

  it('shows an empty state when there are no threads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ threads: [] }) }))
    render(<ThreadHistory activeThreadId="x" onLoad={() => {}} onNew={() => {}} />)
    open()
    expect(await screen.findByText('No saved conversations yet.')).toBeTruthy()
  })

  it('reopens a thread via onLoad', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ threads: [{ id: 't1', title: 'First Q', messages: 2 }] }) }),
    )
    const onLoad = vi.fn()
    render(<ThreadHistory activeThreadId="x" onLoad={onLoad} onNew={() => {}} />)
    open()
    fireEvent.click(await screen.findByText('First Q'))
    expect(onLoad).toHaveBeenCalledWith('t1')
  })

  it('deleting the active thread issues a DELETE and starts a new chat', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: async () => ({ threads: [{ id: 'active', title: 'Active Q', messages: 1 }] }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({}) }) // DELETE
      .mockResolvedValueOnce({ ok: true, json: async () => ({ threads: [] }) }) // refresh
    vi.stubGlobal('fetch', fetchMock)
    const onNew = vi.fn()
    render(<ThreadHistory activeThreadId="active" onLoad={() => {}} onNew={onNew} />)
    open()
    fireEvent.click(await screen.findByLabelText('Delete Active Q'))
    await waitFor(() => expect(onNew).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledWith('/threads/active', { method: 'DELETE' })
  })
})
