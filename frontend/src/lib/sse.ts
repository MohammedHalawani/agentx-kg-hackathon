import type { Artifact, Step } from '../types/contract'

export interface ChatTurn {
  role: string
  content: string
}

export interface StreamHandlers {
  onText: (chunk: string) => void
  onReasoning: (chunk: string) => void
  onStep: (step: Step) => void
  onArtifact: (artifact: Artifact) => void
  onError: (message: string) => void
  onDone: () => void
}

// Minimal SSE-over-fetch reader. We own both ends of the protocol, so it parses the
// `event:` / `data:` frames directly — no streaming-transport dependency needed.
export async function streamChat(
  message: string,
  history: ChatTurn[],
  handlers: StreamHandlers,
  signal?: AbortSignal,
  threadId?: string,
): Promise<void> {
  const res = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history, thread_id: threadId }),
    signal,
  })
  if (!res.ok || !res.body) {
    await res.body?.cancel() // release the error-response stream
    handlers.onError(`Request failed (${res.status})`)
    return
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() ?? '' // keep the trailing partial frame for the next read
    for (const frame of frames) dispatch(frame, handlers)
  }
  if (buffer.trim()) dispatch(buffer, handlers)
}

function dispatch(frame: string, h: StreamHandlers): void {
  let event = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (!data.length) return

  let payload: unknown
  try {
    payload = JSON.parse(data.join('\n'))
  } catch {
    return // skip a malformed/partial frame rather than crashing the read loop
  }
  const p = (payload ?? {}) as { text?: string; message?: string }
  if (event === 'text') h.onText(p.text ?? '')
  else if (event === 'reasoning') h.onReasoning(p.text ?? '')
  else if (event === 'step') {
    if (payload && typeof payload === 'object') h.onStep(payload as Step)
  } else if (event === 'artifact') {
    if (payload && typeof payload === 'object') h.onArtifact(payload as Artifact)
  } else if (event === 'error') h.onError(p.message ?? 'stream error')
  else if (event === 'done') h.onDone()
}
