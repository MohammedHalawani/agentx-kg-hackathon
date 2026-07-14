import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../../hooks/useChatStream'
import { Message } from './Message'

interface ChatThreadProps {
  messages: ChatMessage[]
  onInspect: (message: ChatMessage) => void
  // which message's artifact the side panel is currently showing (split-pane layout)
  activeArtifactId?: string
  onSelectArtifact?: (id: string) => void
}

const NEAR_BOTTOM = 80

export function ChatThread({ messages, onInspect, activeArtifactId, onSelectArtifact }: ChatThreadProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  // stick to the bottom while the reader is there; release it the moment they scroll up to read
  // history. Position alone can't tell us this during a fresh conversation (scrollTop starts 0
  // while content is short), so we track intent explicitly.
  const stick = useRef(true)
  const prevCount = useRef(0)

  useEffect(() => {
    const scroller = scrollRef.current
    const content = contentRef.current
    if (!scroller || !content) return
    // follow the stream: pin to the bottom on any content growth, but only while stuck
    const ro = new ResizeObserver(() => {
      if (stick.current) scroller.scrollTop = scroller.scrollHeight
    })
    ro.observe(content)
    return () => ro.disconnect()
  }, [])

  // a new message (send) always pulls the view down to it, even if the reader had scrolled up
  useEffect(() => {
    if (messages.length > prevCount.current) {
      stick.current = true
      const el = scrollRef.current
      if (el) el.scrollTop = el.scrollHeight
    }
    prevCount.current = messages.length
  }, [messages])

  const onScroll = () => {
    const el = scrollRef.current
    if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM
  }

  return (
    <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
      <div ref={contentRef} className="mx-auto w-full max-w-3xl space-y-4">
        {messages.map((m) => (
          <Message
            key={m.id}
            message={m}
            onInspect={() => onInspect(m)}
            isActiveArtifact={Boolean(onSelectArtifact) && m.id === activeArtifactId}
            onSelectArtifact={onSelectArtifact ? () => onSelectArtifact(m.id) : undefined}
          />
        ))}
      </div>
    </div>
  )
}
