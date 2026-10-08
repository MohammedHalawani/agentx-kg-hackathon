import { useFetch } from '../../hooks/useFetch'
import type { SubGraph } from '../../types/contract'
import { useLanguage } from '@/components/i18n/LanguageProvider'
import { Graph } from '../artifacts/Graph'
import { Skeleton } from '../ui/skeleton'
import { Center, Frame } from './shell'

export function SchemaView() {
  const { data, loading, error, refetch } = useFetch<SubGraph>('/schema')
  const { t } = useLanguage()

  return (
    <Frame>
      {loading ? (
        <Skeleton className="h-full w-full rounded-none" />
      ) : error ? (
        <Center><div role="alert" className="text-center"><p>{t('explore.schemaUnavailable')}</p><button onClick={refetch} className="mt-3 rounded-lg border border-border px-3 py-2">{t('explore.retry')}</button></div></Center>
      ) : data?.nodes?.length ? (
        <Graph graph={data} />
      ) : (
        <Center>{t('explore.schemaUnavailable')}</Center>
      )}
    </Frame>
  )
}
