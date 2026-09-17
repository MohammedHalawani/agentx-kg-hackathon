import { Check, Languages } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { Language } from '@/i18n/messages'
import { useLanguage } from './LanguageProvider'

const OPTIONS: { value: Language; labelKey: string }[] = [
  { value: 'en', labelKey: 'language.english' },
  { value: 'ar', labelKey: 'language.arabic' },
]

export function LanguageToggle() {
  const { language, setLanguage, t } = useLanguage()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size="sm"
            aria-label={t('language.label')}
            className="gap-1.5 px-2 text-muted-foreground hover:text-foreground"
          />
        }
      >
        <Languages className="size-4" />
        <span className="text-xs font-medium uppercase">{language}</span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-36">
        {OPTIONS.map(({ value, labelKey }) => (
          <DropdownMenuItem key={value} onClick={() => setLanguage(value)}>
            {t(labelKey)}
            {language === value && <Check className="ml-auto size-4" />}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
