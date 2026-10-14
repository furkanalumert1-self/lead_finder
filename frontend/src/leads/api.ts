/** Same-origin JSON transport for Lead Radar. The session cookie identifies the person; the
 *  chosen team travels as `X-Treg-Org`, exactly as in the dashboard. */
export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

let org = ''
export function setOrg(slug: string) { org = slug }

export async function api<T = any>(path: string, opts: { method?: string, body?: unknown, raw?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  if (org) headers['X-Treg-Org'] = org
  if (opts.body !== undefined) headers['content-type'] = 'application/json'
  const res = await fetch(path, {
    method: opts.method || 'GET', credentials: 'include', headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  })
  if (!res.ok) {
    const data = await res.json().catch(() => null)
    const detail = typeof data?.detail === 'string' ? data.detail : `HTTP ${res.status}`
    throw new ApiError(res.status, detail)
  }
  return (opts.raw ? res.text() : res.json()) as Promise<T>
}
