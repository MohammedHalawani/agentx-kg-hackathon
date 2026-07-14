import { useState, type ChangeEvent, type KeyboardEvent } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import type { SampleGroup } from '../../types/contract'
import { ExamplesMenu } from './ExamplesMenu'

interface ComposerProps {
  onSend: (text: string) => void
  busy: boolean
  autoFocus?: boolean
  examples?: SampleGroup[]
  onStop?: () => void
}

// Just the input pill. The caller supplies the surrounding chrome: centered + elevated in the
// empty state, docked in a top-bordered bar once a conversation is going.
export function Composer({ onSend, busy, autoFocus, examples, onStop }: ComposerProps) {
  const [value, setValue] = useState('')

  const submit = () => {
    const text = value.trim()
    if (!text || busy) return
    onSend(text)
    setValue('')
  }

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  const autoGrow = (e: ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`
  }

  return (
    <div className="flex w-full items-end gap-2 rounded-2xl border border-hairline bg-surface px-3 py-3 shadow-sm transition-[border-color,box-shadow] duration-200 focus-within:border-accent focus-within:ring-4 focus-within:ring-accent/10">
      {examples && <ExamplesMenu groups={examples} onPick={onSend} />}
      <textarea
        value={value}
        onChange={autoGrow}
        onKeyDown={onKeyDown}
        rows={1}
        autoFocus={autoFocus}
        placeholder="Ask about pollution, housing, or both…"
        className="max-h-32 flex-1 resize-none bg-transparent text-sm leading-relaxed text-ink placeholder:text-muted focus:outline-none"
      />
      {busy && onStop ? (
        <button
          onClick={onStop}
          aria-label="Stop"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-ink text-surface transition-opacity hover:opacity-90"
        >
          <Square size={13} fill="currentColor" />
        </button>
      ) : (
        <button
          onClick={submit}
          disabled={busy || !value.trim()}
          aria-label="Send"
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent text-white transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          <ArrowUp size={16} />
        </button>
      )}
    </div>
  )
}
