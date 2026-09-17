import { useFetch } from '../../hooks/useFetch'
import type { SubGraph } from '../../types/contract'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '../artifacts/Graph'
import { Skeleton } from '../ui/skeleton'
import { Center, Frame } from './shell'

export function SchemaView() {
  const { data, loading } = useFetch<SubGraph>('/schema')
  const { t } = useLanguage()

  return (
    <Frame>
      {loading ? (
        <Skeleton className="h-full w-full rounded-none" />
      ) : data?.nodes?.length ? (
        <Graph graph={data} />
      ) : (
        <Center>{t('explore.schemaUnavailable')}</Center>
      )}
    </Frame>
  )
}
