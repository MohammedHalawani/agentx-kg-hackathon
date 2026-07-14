import { useCallback, useEffect, useRef, useState } from 'react'
import type { Artifact, Step } from '../types/contract'
import { streamChat, type ChatTurn } from '../lib/sse'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  artifact?: Artifact
  steps?: Step[]
  reasoning?: string
  streaming?: boolean
  error?: boolean
}

const nextId = (): string =>
  globalThis.crypto?.randomUUID?.() ?? `m-${Date.now()}-${Math.random().toString(36).slice(2)}`

// The backend caps ChatRequest.history at 20 turns (422 beyond); persisted threads outgrow that
// easily, so send only the newest turns.
const HISTORY_MAX = 20

export interface UseChatStream {
  messages: ChatMessage[]
  busy: boolean
  threadId: string
  send: (text: string) => void
  stop: () => void
  newThread: () => void
  loadThread: (id: string) => void
}

// Messages persist in Neo4j (see backend core.threads), including each answer's artifact (graph/
// map/table/cypher/confidence), so a reloaded thread looks the same as when it was live. Every
// visit starts a FRESH thread - past conversations are never auto-restored; they stay reachable
// through loadThread (the History popover).
export function useChatStream(): UseChatStream {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [threadId, setThreadId] = useState<string>(nextId)
  const messagesRef = useRef<ChatMessage[]>([]) // mirror for reading history without a stale closure
  const threadRef = useRef(threadId)
  const abortRef = useRef<AbortController | null>(null)
  const restoreSeq = useRef(0) // invalidates in-flight restores on switch/new/send so a slow response can't clobber

  useEffect(() => {
    messagesRef.current = messages
  }, [messages])
  useEffect(() => {
    threadRef.current = threadId
  }, [threadId])
  useEffect(() => () => abortRef.current?.abort(), []) // cancel an in-flight stream on unmount

  const restore = useCallback((id: string) => {
    const seq = ++restoreSeq.current
    type StoredMessage = { role: 'user' | 'assistant'; content: string; artifact?: Artifact | null }
    fetch(`/threads/${id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { messages?: StoredMessage[] } | null) => {
        if (seq !== restoreSeq.current) return // superseded by a newer restore/new-thread/send
        setMessages(
          (d?.messages ?? []).map((m) => ({
            id: nextId(),
            role: m.role,
            content: m.content,
            artifact: m.artifact ?? undefined,
          })),
        )
      })
      .catch(() => undefined)
  }, [])

  const send = useCallback(
    (text: string) => {
      const question = text.trim()
      if (!question || busy) return

      restoreSeq.current++ // a restore still in flight must not overwrite the turn we're starting
      const history: ChatTurn[] = messagesRef.current
        .slice(-HISTORY_MAX)
        .map((m) => ({ role: m.role, content: m.content }))
      const botId = nextId()
      setMessages((prev) => [
        ...prev,
        { id: nextId(), role: 'user', content: question },
        { id: botId, role: 'assistant', content: '', streaming: true },
      ])
      setBusy(true)

      const patch = (fn: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => prev.map((m) => (m.id === botId ? fn(m) : m)))

      const ctrl = new AbortController()
      abortRef.current = ctrl

      streamChat(
        question,
        history,
        {
          onText: (chunk) => patch((m) => ({ ...m, content: m.content + chunk })),
          onReasoning: (chunk) => patch((m) => ({ ...m, reasoning: (m.reasoning ?? '') + chunk })),
          onStep: (step) => patch((m) => ({ ...m, steps: [...(m.steps ?? []), step] })),
          onArtifact: (artifact) => patch((m) => ({ ...m, artifact })),
          onError: (msg) =>
            patch((m) => ({
              ...m,
              content: m.content || `Something went wrong (${msg}). Please try again.`,
              error: true,
            })),
          onDone: () => patch((m) => ({ ...m, streaming: false })),
        },
        ctrl.signal,
        threadRef.current,
      )
        .catch((err: unknown) => {
          if (err instanceof DOMException && err.name === 'AbortError') return // user/unmount cancel
          patch((m) => ({
            ...m,
            content: m.content || 'Connection lost. Is the backend running?',
            error: true,
          }))
        })
        .finally(() => {
          patch((m) => ({ ...m, streaming: false }))
          setBusy(false)
          abortRef.current = null
        })
    },
    [busy],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const newThread = useCallback(() => {
    abortRef.current?.abort()
    restoreSeq.current++ // drop any in-flight restore so it can't repopulate the cleared thread
    setMessages([])
    setThreadId(nextId())
  }, [])

  const loadThread = useCallback(
    (id: string) => {
      abortRef.current?.abort()
      setThreadId(id)
      restore(id)
    },
    [restore],
  )

  return { messages, busy, threadId, send, stop, newThread, loadThread }
}
