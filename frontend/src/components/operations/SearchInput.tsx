import { Search } from 'lucide-react'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/cn'

export function SearchInput({
  value,
  onChange,
  placeholder,
  className,
  id = 'ops-search',
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  id?: string
}) {
  const { t } = useLanguage()
  return (
    <div className={cn('relative min-w-0 flex-1', className)}>
      <Search size={15} className="pointer-events-none absolute top-1/2 start-3 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
      <Input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? t('common.search')}
        aria-label={placeholder ?? t('common.search')}
        className="ps-9"
      />
    </div>
  )
}
