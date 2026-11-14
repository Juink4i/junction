// Turns server data into display steps. Only maps what already happened to a picture;
// whether an order is allowed is decided by the trade server, never here.

import type { AgentEvent, Order, OptionCard } from './types'

export type StepState = 'todo' | 'active' | 'done' | 'skipped' | 'stopped'

export interface Step {
  key: string
  title: string
  who: 'agent' | 'code' | 'person' | 'valio'
  state: StepState
  detail: string
  time?: string | null
}

// ---------------------------------------------------------------------------
// Live run: what the agent and server are doing right now (Overview page).

export interface RunView {
  runId: string | null
  scene: { title?: string; subtitle?: string } | null
  request: string | null
  steps: Step[]
  quote: QuoteView | null
  options: { title?: string; options: OptionCard[] } | null
  decision: { status: string; reasons: string[]; question?: string | null; order_id?: string | null } | null
  finished: boolean
}

export interface QuoteView {
  quote_id: string
  total_eur: number
  total_with_tax_eur?: number
  expires_at?: string
  lines: Array<Record<string, unknown>>
}

const SHOP_TOOLS = new Set(['record_request', 'search_products', 'get_product'])

function asQuote(result: unknown): QuoteView | null {
  if (result && typeof result === 'object' && 'quote_id' in result && 'lines' in result) {
    return result as QuoteView
  }
  return null
}

/** Events of the most recent run (plus the scene card that introduced it). */
export function latestRun(events: AgentEvent[]): AgentEvent[] {
  let start = -1
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].kind === 'run_start') {
      start = i
      break
    }
  }
  if (start < 0) return events.filter((e) => e.kind !== 'clear')
  const runId = events[start].run_id
  const before = start > 0 && events[start - 1].kind === 'scene' ? [events[start - 1]] : []
  return [...before, ...events.slice(start).filter((e) => !runId || e.run_id === runId || e.kind === 'scene')]
}

export function runView(all: AgentEvent[]): RunView {
  const events = latestRun(all)
  const view: RunView = {
    runId: null,
    scene: null,
    request: null,
    steps: [],
    quote: null,
    options: null,
    decision: null,
    finished: false,
  }
  let shop: StepState = 'todo'
  let compare: StepState = 'todo'
  let rules: StepState = 'todo'
  let person: StepState = 'todo'
  let shopDetail = 'Waiting for a request.'
  let compareDetail = 'Compares options and asks for a signed quote.'
  let rulesDetail = "Checks the order against the buyer's signed mandate."
  let personDetail = 'Only needed when the rules say so.'
  let searches = 0

  for (const e of events) {
    switch (e.kind) {
      case 'scene':
        view.scene = { title: e.title, subtitle: e.subtitle }
        break
      case 'run_start':
        view.runId = e.run_id ?? null
        view.request = typeof e.request === 'string' ? e.request : view.request
        shop = 'active'
        shopDetail = 'Reading the request.'
        break
      case 'user':
        view.request = e.text ?? view.request
        if (shop === 'todo') shop = 'active'
        break
      case 'tool_call':
        if (SHOP_TOOLS.has(e.tool ?? '')) {
          shop = 'active'
          if (e.tool === 'search_products') {
            searches += 1
            shopDetail = `Searching the product file (${searches} ${searches === 1 ? 'search' : 'searches'}).`
          } else if (e.tool === 'get_product') {
            shopDetail = 'Reading product details and allergens.'
          }
        } else if (e.tool === 'request_quote') {
          shop = 'done'
          compare = 'active'
          compareDetail = 'Asking Valio Aimo for price and delivery.'
        } else if (e.tool === 'place_order') {
          shop = 'done'
          compare = 'done'
          rules = 'active'
          rulesDetail = 'Checking limits, categories, allergens and delivery date.'
        }
        break
      case 'tool_result':
        if (e.tool === 'request_quote') {
          const q = asQuote(e.result)
          if (q) {
            view.quote = q
            compareDetail = `Signed quote ${q.quote_id}, valid 15 minutes.`
          } else {
            compareDetail = 'No quote: the agent is trying another way.'
          }
        }
        break
      case 'options':
        shop = 'done'
        compare = 'active'
        view.options = { title: e.title, options: e.options ?? [] }
        compareDetail = `Compared ${e.options?.length ?? 0} options.`
        break
      case 'decision': {
        const s = e.status ?? ''
        if (s === 'approved' || s === 'rejected' || s === 'pending') {
          // A person's decision on an approval.
          if (s === 'pending') {
            person = 'active'
          } else {
            person = s === 'approved' ? 'done' : 'stopped'
            personDetail = `${s === 'approved' ? 'Approved' : 'Rejected'}${e.decided_by ? ` by ${e.decided_by}` : ''}.`
            view.decision = {
              status: s === 'approved' ? 'confirmed' : 'rejected',
              reasons: [personDetail],
              order_id: view.decision?.order_id,
            }
          }
        } else {
          shop = 'done'
          compare = 'done'
          rules = s === 'rejected' ? 'stopped' : 'done'
          rulesDetail = (e.reasons ?? [])[0] ?? statusLabel(s)
          view.decision = { status: s, reasons: e.reasons ?? [], question: e.question, order_id: e.order_id }
          if (s === 'pending_approval') {
            person = 'active'
            personDetail = 'Waiting for a person to approve.'
          } else if (s === 'needs_clarification') {
            person = 'active'
            personDetail = 'The buyer must confirm the amount.'
          } else if (person === 'todo' || person === 'active') {
            person = 'skipped'
            personDetail = s === 'confirmed' ? 'Not needed: within the mandate.' : 'Not possible: a hard rule was broken.'
          }
        }
        break
      }
      case 'ask':
        person = 'active'
        personDetail = e.question ?? 'The agent asked the buyer.'
        break
      case 'answer':
        personDetail = `Buyer answered: “${e.text ?? ''}”`
        break
      case 'waiting':
        person = 'active'
        personDetail = 'Waiting for a person to approve.'
        break
      case 'run_end':
        view.finished = true
        break
    }
  }
  if (view.finished && shop === 'active') shop = 'done'

  view.steps = [
    { key: 'shop', title: 'Shopper', who: 'agent', state: shop, detail: shopDetail },
    { key: 'compare', title: 'Compare & quote', who: 'agent', state: compare, detail: compareDetail },
    { key: 'rules', title: 'Server rules', who: 'code', state: rules, detail: rulesDetail },
    { key: 'person', title: 'Person', who: 'person', state: person, detail: personDetail },
  ]
  return view
}

// ---------------------------------------------------------------------------
// One order: from quote to delivery (Order detail page).

export function statusLabel(status: string): string {
  return (
    {
      confirmed: 'Confirmed',
      needs_clarification: 'Needs clarification',
      pending_approval: 'Pending approval',
      rejected: 'Rejected',
      approved: 'Approved',
      pending: 'Pending',
    } as Record<string, string>
  )[status] ?? status
}

export function orderSteps(order: Order, today: Date = new Date()): Step[] {
  const log = order.log ?? []
  const at = (pred: (action: string) => boolean) => log.find((l) => pred(l.action))?.time ?? null
  const quotedAt = at((a) => a === 'request_quote') ?? order.created_at
  const decidedAt = at((a) => a.startsWith('decision:')) ?? order.created_at
  const firstDecision = log.find((l) => l.action.startsWith('decision:'))?.action.slice('decision:'.length)
  const approval = order.approval
  const status = order.status

  const steps: Step[] = [
    {
      key: 'quoted',
      title: 'Quoted',
      who: 'valio',
      state: 'done',
      detail: `Signed quote, ${order.lines.length} ${order.lines.length === 1 ? 'line' : 'lines'}.`,
      time: quotedAt,
    },
  ]

  const rulesStopped = !approval && status === 'rejected'
  steps.push({
    key: 'rules',
    title: 'Rules checked',
    who: 'code',
    state: rulesStopped ? 'stopped' : 'done',
    detail: statusLabel(firstDecision ?? status),
    time: decidedAt,
  })

  if (approval) {
    steps.push({
      key: 'approval',
      title: 'Approval',
      who: 'person',
      state: approval.status === 'pending' ? 'active' : approval.status === 'approved' ? 'done' : 'stopped',
      detail:
        approval.status === 'pending'
          ? `Waiting for ${approval.approvers[0] ?? 'a person'}.`
          : `${statusLabel(approval.status)} by ${approval.decided_by ?? 'a person'}.`,
      time: approval.decided_at,
    })
  } else if (status === 'needs_clarification') {
    steps.push({
      key: 'approval',
      title: 'Buyer confirms',
      who: 'person',
      state: 'active',
      detail: order.question ?? 'The buyer must confirm the amount.',
    })
  } else {
    steps.push({
      key: 'approval',
      title: 'Approval',
      who: 'person',
      state: status === 'rejected' ? 'todo' : 'skipped',
      detail: status === 'rejected' ? 'Not possible after a hard rule.' : 'Not needed: within the mandate.',
    })
  }

  const confirmed = status === 'confirmed'
  steps.push({
    key: 'confirmed',
    title: 'Order placed',
    who: 'valio',
    state: confirmed ? 'done' : status === 'rejected' ? 'stopped' : 'todo',
    detail: confirmed ? 'Sent to Valio Aimo.' : status === 'rejected' ? 'Not sent. Nobody can override.' : 'Not yet.',
    time: confirmed ? (approval?.decided_at ?? decidedAt) : null,
  })

  const arrives = order.delivery_date
  const arrived = confirmed && !!arrives && new Date(`${arrives}T23:59:59`) < today
  steps.push({
    key: 'delivery',
    title: arrived ? 'Delivery date passed' : 'Delivery',
    who: 'valio',
    state: !confirmed ? 'todo' : arrived ? 'done' : 'active',
    detail: status === 'rejected' ? 'No delivery.' : !confirmed ? 'Once the order is placed.' : arrives ? `Arrives ${arrives}` : 'Date not given.',
    time: null,
  })
  return steps
}

// ---------------------------------------------------------------------------
// The buyer's view of a delivery: four stages. Valio Aimo shares no tracking yet, so
// "Out for delivery" and "Delivered" are shown in the diagram but never marked reached.

export function deliverySteps(order: Order): Step[] {
  const { status, approval } = order
  const confirmed = status === 'confirmed'
  const rejected = status === 'rejected'
  const confirmingDetail = confirmed
    ? approval?.decided_by
      ? `Approved by ${approval.decided_by}.`
      : 'Within your rules.'
    : rejected
      ? (order.reasons.at(-1) ?? 'Rejected.')
      : status === 'needs_clarification'
        ? 'Waiting for you to confirm the amount.'
        : `Waiting for approval${approval?.approvers?.[0] ? ` from ${approval.approvers[0]}` : ''}.`
  return [
    {
      key: 'confirming',
      title: 'Confirming order',
      who: 'code',
      state: confirmed ? 'done' : rejected ? 'stopped' : 'active',
      detail: confirmingDetail,
      time: confirmed ? (approval?.decided_at ?? order.created_at) : null,
    },
    {
      key: 'preparing',
      title: 'Preparing order',
      who: 'valio',
      state: confirmed ? 'active' : 'todo',
      detail: confirmed ? 'Valio Aimo is preparing it.' : rejected ? 'Not sent.' : 'Once the order is confirmed.',
    },
    {
      key: 'out',
      title: 'Out for delivery',
      who: 'valio',
      state: 'todo',
      detail: confirmed && order.delivery_date ? `Planned for ${order.delivery_date}` : '—',
    },
    {
      key: 'delivered',
      title: 'Delivered',
      who: 'valio',
      state: 'todo',
      detail: confirmed && order.delivery_date ? `Expected ${order.delivery_date}` : '—',
    },
  ]
}

// ---------------------------------------------------------------------------
// Where an order is in its life, for the operations dashboard. "Shipping" and
// "completed" follow Valio Aimo's promised delivery date: there is no live tracking.

export type Phase = 'awaiting_input' | 'awaiting_approval' | 'approved' | 'shipping' | 'completed' | 'rejected'

export const PHASES: { key: Phase; label: string; hint: string }[] = [
  { key: 'awaiting_input', label: 'Awaiting buyer input', hint: 'The server asked the buyer to confirm an unusual amount.' },
  { key: 'awaiting_approval', label: 'Awaiting approval', hint: 'Outside the mandate: a person at the buyer must approve.' },
  { key: 'approved', label: 'Approved', hint: 'Confirmed; delivery date still ahead.' },
  { key: 'shipping', label: 'Shipping today', hint: 'Confirmed; the promised delivery date is today.' },
  { key: 'completed', label: 'Completed', hint: 'Confirmed; the promised delivery date has passed.' },
  { key: 'rejected', label: 'Rejected', hint: 'A hard rule was broken or a person said no.' },
]

function localDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function orderPhase(order: Pick<Order, 'status' | 'delivery_date'>, today: Date = new Date()): Phase {
  if (order.status === 'needs_clarification') return 'awaiting_input'
  if (order.status === 'pending_approval') return 'awaiting_approval'
  if (order.status === 'rejected') return 'rejected'
  const day = localDay(today)
  if (!order.delivery_date || order.delivery_date > day) return 'approved'
  return order.delivery_date === day ? 'shipping' : 'completed'
}

export function progressFraction(steps: Step[]): number {
  const counted = steps.filter((s) => s.state !== 'skipped')
  if (counted.length === 0) return 0
  const done = counted.filter((s) => s.state === 'done').length
  const active = counted.some((s) => s.state === 'active') ? 0.5 : 0
  return Math.min(1, (done + active) / counted.length)
}
