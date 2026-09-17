import { useEffect, useState } from 'react'
import { useLanguage } from './LanguageProvider'
import { cachedArabic, translateToArabic } from '@/lib/translate'

/**
 * One piece of the agent's own free-text reasoning, rendered in the interface language.
 *
 * The agent reasons and writes back in its original language; this translates a copy for
 * display only, and only when the interface is set to Arabic. In English it renders the
 * agent's text verbatim with no request and no extra state - the original code path.
 *
 * Use it for model prose (a rationale, a review reason). Do NOT use it for a category, an
 * action, an id, a score or anything else that is graph vocabulary or a decision: those are
 * translated from fixed dictionaries (rootCauseLabel/entityLabel) or shown as-is on purpose.
 */
export function AgentProse({ text }: { text: string }) {
  const { isArabic } = useLanguage()
  // start from the cache so a case reopened later renders Arabic on the first paint
  const [translated, setTranslated] = useState<string | undefined>(() =>
    isArabic ? cachedArabic(text) : undefined,
  )

  useEffect(() => {
    if (!isArabic) return
    const hit = cachedArabic(text)
    if (hit !== undefined) {
      setTranslated(hit)
      return
    }
    let live = true
    setTranslated(undefined)
    translateToArabic(text).then((value) => {
      if (live) setTranslated(value)
    })
    return () => {
      live = false
    }
  }, [isArabic, text])

  // Until the translation lands, the agent's own words - never a spinner or a blank line.
  const shown = isArabic ? translated ?? text : text
  // dir="auto" because the shell stays LTR in both languages; the paragraph itself flips.
  return (
    <span dir="auto" className="inline-block">
      {shown}
    </span>
  )
}
