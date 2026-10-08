let localSession: Promise<string> | null = null

// Session is memory-only. The server authenticates its local origin and sets the role.
async function token(): Promise<string> {
  localSession ??= fetch('/operations/session', { credentials: 'same-origin' })
    .then(async response => {
      if (!response.ok) throw new Error(`Request failed (${response.status})`)
      const body = await response.json() as { token?: string; nonce?: string }
      const value = body.token ?? body.nonce
      if (!value) throw new Error('Operations session unavailable')
      return value
    }).catch(error => { localSession = null; throw error })
  return localSession
}

export async function operationsPost<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const nonce = await token()
  const response = await fetch(path, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Operations-Token': nonce }, body: JSON.stringify(body) })
  if (!response.ok) { if (response.status === 401 || response.status === 403) localSession = null; throw new Error(`Request failed (${response.status})`) }
  return response.json() as Promise<T>
}
