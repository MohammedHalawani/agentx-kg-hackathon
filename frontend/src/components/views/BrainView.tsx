import { RefreshCw } from 'lucide-react'
import { useFetch } from '../../hooks/useFetch'
import type { SubGraph } from '../../types/contract'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '../artifacts/Graph'
import { Skeleton } from '../ui/skeleton'
import { Center, Frame } from './shell'

export function BrainView() {
  const { data, loading, refetch } = useFetch<SubGraph>('/graph')
  const { t } = useLanguage()

  return (
    <Frame>
      <div className="relative h-full w-full">
        {loading ? (
          <Skeleton className="h-full w-full rounded-none" />
        ) : data?.nodes?.length ? (
          <Graph graph={data} />
        ) : (
          <Center>{t('explore.noGraphData')}</Center>
        )}
        <button
          onClick={refetch}
          disabled={loading}
          className="absolute bottom-3 left-3 z-10 inline-flex items-center gap-1.5 rounded-lg border border-border bg-card/90 px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground backdrop-blur transition-colors hover:text-foreground disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : undefined} />
          {t('explore.showAnother')}
        </button>
      </div>
    </Frame>
  )
}
