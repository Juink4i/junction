import { useEffect, useRef, useState } from "react"
import type { AgentEvent } from "./types"

export type LinkState = "connecting" | "live" | "offline"

/**
 * Every event the agent and the demo have sent, replayed on connect and then live (SSE).
 * A "clear" event, or ids starting again from 1 after a server restart, empties the list.
 */
export function useEventStream(onEvent?: (e: AgentEvent) => void) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [link, setLink] = useState<LinkState>("connecting")
  const handler = useRef(onEvent)
  handler.current = onEvent

  useEffect(() => {
    let lastId = 0
    const src = new EventSource("/api/events/stream")
    src.onopen = () => setLink("live")
    src.onerror = () => setLink("offline")
    src.onmessage = (m) => {
      let e: AgentEvent
      try {
        e = JSON.parse(m.data)
      } catch {
        return
      }
      const id = e.id ?? 0
      if (id && id === lastId) return // a duplicate after reconnecting
      const restarted = id && id < lastId && e.kind !== "clear"
      lastId = id || lastId
      setEvents((prev) => (e.kind === "clear" ? [] : restarted ? [e] : [...prev, e]))
      handler.current?.(e)
    }
    return () => src.close()
  }, [])

  return { events, link }
}

/** Call fn now and then every `ms`, while `enabled`. Waits for each call to finish. */
export function usePoll(fn: () => Promise<void>, ms: number, enabled = true) {
  const saved = useRef(fn)
  saved.current = fn
  useEffect(() => {
    if (!enabled) return
    let stop = false
    let timer: ReturnType<typeof setTimeout>
    const tick = async () => {
      await saved.current().catch(() => {})
      if (!stop) timer = setTimeout(tick, ms)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
    }
  }, [ms, enabled])
}
