import { useFetch } from './useFetch'
import type { ApiPage } from '@/adapters/operationsApi'

export function useOperationsPage<T>(url: string) {
  const result = useFetch<ApiPage<T>>(url)
  const page = result.data
  const cursorValid = (value: unknown) => value === null || typeof value === 'string'
  const valid = page == null || (Array.isArray(page.items) && typeof page.filtered_total === 'number' && Number.isFinite(page.filtered_total) && cursorValid(page.next_cursor) && cursorValid(page.previous_cursor))
  return { ...result, data: valid ? page : null, error: result.error ?? (valid ? null : 'Unexpected operational response') }
}
