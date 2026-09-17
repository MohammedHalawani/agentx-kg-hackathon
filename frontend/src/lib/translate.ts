/**
 * Display-only translation of agent prose, for when the interface language is Arabic.
 *
 * The agent's own output is never changed: this fetches a translated *copy* of a rationale
 * for rendering, keyed on the exact source string. Scores, ids, precedent references and
 * everything written back to the graph stay in their original form - see chat/llm/translate.py.
 *
 * Three things keep it off the render path's critical line:
 *   - English is a pure no-op. No cache lookup, no request, no state update, so the existing
 *     view behaves exactly as it did.
 *   - one process-lifetime cache keyed by source text, so a rationale is translated once
 *     however often the case is re-rendered, collapsed, reopened or revisited.
 *   - requests made in the same tick are coalesced into a single POST, because a finished
 *     run reveals several rationales at once.
 * Until a translation arrives the original text is shown, so nothing ever renders empty.
 */

const cache = new Map<string, string>()
const inFlight = new Map<string, Promise<string>>()

// requests collected within one tick, flushed together
let pending: { text: string; resolve: (value: string) => void }[] = []
let scheduled = false

async function flush(): Promise<void> {
  const batch = pending
  pending = []
  scheduled = false
  const texts = batch.map((b) => b.text)
  try {
    const res = await fetch('/translate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texts, target: 'ar' }),
    })
    if (!res.ok) throw new Error(`translate failed: ${res.status}`)
    const data = (await res.json()) as { texts?: unknown }
    const out = Array.isArray(data.texts) ? data.texts : []
    batch.forEach((item, i) => {
      // the backend hands back the original text when it cannot translate safely, so an
      // entry that comes back unchanged is a legitimate answer, not a failure to retry
      const value = typeof out[i] === 'string' && out[i] ? (out[i] as string) : item.text
      cache.set(item.text, value)
      item.resolve(value)
    })
  } catch {
    // fall back to the original prose; don't cache, so a later render may retry
    batch.forEach((item) => item.resolve(item.text))
  } finally {
    batch.forEach((item) => inFlight.delete(item.text))
  }
}

/** The Arabic rendering of one piece of agent prose, from cache when it has been seen before. */
export function translateToArabic(text: string): Promise<string> {
  const hit = cache.get(text)
  if (hit !== undefined) return Promise.resolve(hit)
  const running = inFlight.get(text)
  if (running) return running

  const promise = new Promise<string>((resolve) => {
    pending.push({ text, resolve })
    if (!scheduled) {
      scheduled = true
      queueMicrotask(flush)
    }
  })
  inFlight.set(text, promise)
  return promise
}

/** A translation already in hand for this exact text, if any - lets a render start correct. */
export function cachedArabic(text: string): string | undefined {
  return cache.get(text)
}

/** Test seam: forget everything translated so far. */
export function __resetTranslationCache(): void {
  cache.clear()
  inFlight.clear()
  pending = []
  scheduled = false
}
