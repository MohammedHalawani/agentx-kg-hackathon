import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { getMessage, interpolate, messages, type Language } from '@/i18n/messages'
import { humanizeKey } from '@/lib/humanizeKey'

const STORAGE_KEY = 'agentx-language'

export type TranslationKey = string

interface LanguageContextValue {
  language: Language
  setLanguage: (language: Language) => void
  isArabic: boolean
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string
  rootCauseLabel: (rawKey: string) => string
  entityLabel: (label: string) => string
  propertyLabel: (key: string) => string
}

const LanguageContext = createContext<LanguageContextValue | null>(null)

function readStoredLanguage(): Language {
  if (typeof window === 'undefined') return 'en'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored === 'en' || stored === 'ar') return stored
  return 'en'
}

// `lang` is the hook the stylesheet uses: :root[lang='ar'] switches text blocks to
// unicode-bidi: plaintext, so each one takes its direction from its own content (see
// index.css). `dir` stays ltr on purpose - the frame does not mirror, only the text in it.
function applyLanguage(language: Language) {
  const root = document.documentElement
  root.lang = language
  root.dir = 'ltr'
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readStoredLanguage)

  useEffect(() => {
    applyLanguage(language)
  }, [language])

  const setLanguage = useCallback((next: Language) => {
    localStorage.setItem(STORAGE_KEY, next)
    setLanguageState(next)
  }, [])

  const t = useCallback(
    (key: TranslationKey, vars?: Record<string, string | number>) => {
      const msg = getMessage(messages[language], key) ?? getMessage(messages.en, key) ?? key
      return vars ? interpolate(msg, vars) : msg
    },
    [language],
  )

  const rootCauseLabel = useCallback(
    (rawKey: string) => {
      const escalated = rawKey.startsWith('escalation:')
      const base = escalated ? rawKey.slice('escalation:'.length) : rawKey
      const normalized = base.replace(/_/g, ' ')
      const translated =
        messages[language].rootCauses[normalized as keyof typeof messages.en.rootCauses]
      const display = translated ?? normalized
      return escalated ? `${display} ${t('common.escalated')}` : display
    },
    [language, t],
  )

  const entityLabel = useCallback(
    (label: string) =>
      messages[language].entities[label as keyof typeof messages.en.entities] ?? label,
    [language],
  )

  const propertyLabel = useCallback(
    (key: string) =>
      messages[language].properties[key as keyof typeof messages.en.properties] ?? humanizeKey(key),
    [language],
  )

  const value = useMemo(
    () => ({
      language,
      setLanguage,
      isArabic: language === 'ar',
      t,
      rootCauseLabel,
      entityLabel,
      propertyLabel,
    }),
    [language, setLanguage, t, rootCauseLabel, entityLabel, propertyLabel],
  )

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>
}

export function useLanguage(): LanguageContextValue {
  const ctx = useContext(LanguageContext)
  if (!ctx) throw new Error('useLanguage must be used within LanguageProvider')
  return ctx
}
