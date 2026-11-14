// Fetch helpers. Every call goes to this web server, which forwards to the trade server.

export async function getJSON<T = unknown>(url: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(url, { cache: "no-store", ...opts })
  let body: unknown = null
  try {
    body = await res.json()
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const b = body as { message?: string; detail?: string } | null
    throw new Error(b?.message || b?.detail || `${res.status} ${res.statusText}`)
  }
  return body as T
}

export const postJSON = <T = unknown>(url: string, body?: unknown): Promise<T> =>
  getJSON<T>(url, {
    method: "POST",
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

/** Accept either a bare list or {items|entries|approvals: [...]}. */
export function asList<T>(body: unknown, ...keys: string[]): T[] {
  if (Array.isArray(body)) return body as T[]
  const obj = body as Record<string, unknown> | null
  for (const k of keys) if (obj && Array.isArray(obj[k])) return obj[k] as T[]
  return []
}
