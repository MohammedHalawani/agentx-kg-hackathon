import { ar } from './ar'
import { en, type Messages } from './en'

export type Language = 'en' | 'ar'

export const messages: Record<Language, Messages> = { en, ar }

export type { Messages }

/** Walk a dot-separated path into the nested message object. */
export function getMessage(obj: Messages, path: string): string | undefined {
  let cur: unknown = obj
  for (const part of path.split('.')) {
    if (cur == null || typeof cur !== 'object') return undefined
    cur = (cur as Record<string, unknown>)[part]
  }
  return typeof cur === 'string' ? cur : undefined
}

/** Replace `{key}` placeholders in a template string. */
export function interpolate(
  template: string,
  vars: Record<string, string | number>,
): string {
  return template.replace(/\{(\w+)\}/g, (_, key: string) =>
    vars[key] !== undefined ? String(vars[key]) : `{${key}}`,
  )
}
