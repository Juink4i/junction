// Talks only to the web/ backend-for-frontend (/api on the same origin).
// Every account view goes through /api/accounts/{buyer_id}/..., which the backend scopes
// to that one account, so the browser never receives another account's data.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ApiError, AgentEvent } from './types'

export class ApiFailure extends Error {
  code: string
  retryable: boolean
  constructor(err: ApiError) {
    super(err.message)
    this.code = err.code
    this.retryable = !!err.retryable
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`/api${path}`, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiFailure({ code: 'offline', message: 'The web server is not answering.', retryable: true })
  }
  const text = await res.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    body = null
  }
  if (!res.ok) {
    const err = (body && typeof body === 'object' && 'message' in body ? body : null) as ApiError | null
    throw new ApiFailure(err ?? { code: `http_${res.status}`, message: `Request failed (${res.status}).`, retryable: res.status >= 500 })
  }
  return body as T
}

export const accountPath = (buyer: string, rest = '') => `/accounts/${encodeURIComponent(buyer)}${rest}`

export interface Loaded<T> {
  data: T | null
  error: ApiFailure | null
  loading: boolean
  reload: () => void
}

/** Fetch `path`, and again every `everyMs` (if given). Keeps the last good data on errors. */
export function usePoll<T>(path: string | null, everyMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<ApiFailure | null>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  const current = useRef(path)

  useEffect(() => {
    if (current.current !== path) {
      current.current = path
      setData(null)
      setLoading(true)
    }
    if (!path) return
    let alive = true
    const load = () =>
      api<T>(path)
        .then((d) => {
          if (!alive) return
          setData(d)
          setError(null)
        })
        .catch((e: ApiFailure) => alive && setError(e))
        .finally(() => alive && setLoading(false))
    load()
    const timer = everyMs ? window.setInterval(load, everyMs) : undefined
    return () => {
      alive = false
      if (timer) window.clearInterval(timer)
    }
  }, [path, everyMs, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  return { data, error, loading, reload }
}

/** Live agent events for one account (server-side filtered by ?buyer=). */
export function useEvents(buyer: string | null): { events: AgentEvent[]; live: boolean } {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [live, setLive] = useState(false)

  useEffect(() => {
    setEvents([])
    if (!buyer) return
    const src = new EventSource(`/api/events/stream?buyer=${encodeURIComponent(buyer)}`)
    src.onopen = () => setLive(true)
    src.onerror = () => setLive(false)
    src.onmessage = (msg) => {
      try {
        const e = JSON.parse(msg.data) as AgentEvent
        if (e.kind === 'clear') setEvents([])
        else setEvents((prev) => (prev.some((p) => p.id === e.id) ? prev : [...prev, e]))
      } catch {
        /* ignore a malformed frame */
      }
    }
    return () => {
      src.close()
      setLive(false)
    }
  }, [buyer])

  return { events, live }
}
