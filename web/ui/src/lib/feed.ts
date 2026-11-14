import type { AgentEvent } from "./types"

// Turns the raw event list into what the chat shows: a tool call and its result become one
// row, and a "waiting for a person" row learns how the wait ended.

export type FeedItem =
  | { type: "scene"; key: string; e: AgentEvent }
  | { type: "run_start"; key: string; e: AgentEvent }
  | { type: "buyer"; key: string; text: string }
  | { type: "agent"; key: string; text: string; scripted: boolean }
  | { type: "ask"; key: string; text: string }
  | { type: "request"; key: string; e: AgentEvent }
  | { type: "tool"; key: string; call: AgentEvent; result?: AgentEvent }
  | { type: "options"; key: string; e: AgentEvent }
  | { type: "waiting"; key: string; e: AgentEvent; ended?: "approved" | "rejected" | "pending" }
  | { type: "decision"; key: string; e: AgentEvent }
  | { type: "verify"; key: string; e: AgentEvent }
  | { type: "onboarded"; key: string; e: AgentEvent }
  | { type: "note"; key: string; text: string }

export function buildFeed(events: AgentEvent[]): FeedItem[] {
  const items: FeedItem[] = []
  const calls = new Map<string, number>()
  const waits = new Map<string, number>()
  let scripted = false

  events.forEach((e, i) => {
    const key = String(e.id ?? `i${i}`)
    switch (e.kind) {
      case "scene":
        items.push({ type: "scene", key, e })
        break
      case "run_start":
        scripted = String(e.model ?? "").startsWith("scripted")
        items.push({ type: "run_start", key, e })
        break
      case "user":
      case "answer":
        items.push({ type: "buyer", key, text: e.text ?? "" })
        break
      case "agent":
        items.push({ type: "agent", key, text: e.text ?? "", scripted })
        break
      case "ask":
        items.push({ type: "ask", key, text: e.question ?? "" })
        break
      case "request":
        items.push({ type: "request", key, e })
        break
      case "tool_call":
        if (e.call_id) calls.set(e.call_id, items.length)
        items.push({ type: "tool", key, call: e })
        break
      case "tool_result": {
        const at = e.call_id ? calls.get(e.call_id) : undefined
        const item = at === undefined ? undefined : items[at]
        if (item?.type === "tool") items[at!] = { ...item, result: e }
        break
      }
      case "options":
        items.push({ type: "options", key, e })
        break
      case "waiting":
        if (e.approval_id) waits.set(e.approval_id, items.length)
        items.push({ type: "waiting", key, e })
        break
      case "decision": {
        const at = e.approval_id ? waits.get(e.approval_id) : undefined
        const item = at === undefined ? undefined : items[at]
        if (item?.type === "waiting" && (e.status === "approved" || e.status === "rejected" || e.status === "pending"))
          items[at!] = { ...item, ended: e.status }
        items.push({ type: "decision", key, e })
        break
      }
      case "verify":
        items.push({ type: "verify", key, e })
        break
      case "onboarded":
        items.push({ type: "onboarded", key, e })
        break
      case "note":
        items.push({ type: "note", key, text: e.text ?? "" })
        break
      case "run_end":
        if (e.error) items.push({ type: "note", key, text: `The agent stopped: ${e.error}` })
        break
    }
  })
  return items
}

/** The scene playing now, if any: the last scene event since the last clear. */
export function currentScene(events: AgentEvent[]): AgentEvent | undefined {
  for (let i = events.length - 1; i >= 0; i--) if (events[i].kind === "scene") return events[i]
  return undefined
}
