import { describe, expect, it } from 'vitest'
import { deliverySteps, orderPhase, orderSteps, runView } from './pipeline'

describe('deliverySteps (the buyer’s four stages)', () => {
  const base = {
    order_id: 'o', quote_id: 'q', created_at: '2026-11-14T09:00:00Z', rationale: '',
    total_eur: 1, total_with_tax_eur: 1, lines: [], expires_at: null, delivery_date: '2026-11-16', approval: null,
  }
  const states = (o: object) => deliverySteps({ ...base, status: 'confirmed', reasons: [], ...o } as never).map((s) => s.state)

  it('names the four stages in order', () => {
    expect(deliverySteps({ ...base, status: 'confirmed', reasons: [] }).map((s) => s.title)).toEqual([
      'Confirming order', 'Preparing order', 'Out for delivery', 'Delivered'])
  })
  it('confirmed: confirming done, preparing in progress, the last two still to come', () => {
    expect(states({})).toEqual(['done', 'active', 'todo', 'todo'])
  })
  it('waiting on a person: still confirming', () => {
    expect(states({ status: 'pending_approval' })).toEqual(['active', 'todo', 'todo', 'todo'])
  })
  it('withdrawn: confirming skipped, with the reason, nothing after it', () => {
    const steps = deliverySteps({ ...base, status: 'withdrawn', reasons: ['Over the limit.', 'Withdrawn: replaced.'] })
    expect(steps.map((s) => s.state)).toEqual(['skipped', 'todo', 'todo', 'todo'])
    expect(steps[0].detail).toBe('Withdrawn: replaced.')
  })
  it('rejected: stops at confirming', () => {
    expect(states({ status: 'rejected', reasons: ['Category not allowed.'] })).toEqual(['stopped', 'todo', 'todo', 'todo'])
  })
})

describe('orderPhase', () => {
  const today = new Date(2026, 10, 16, 12) // 16 Nov 2026, local time
  it('maps outcomes and delivery dates to phases', () => {
    expect(orderPhase({ status: 'pending_approval', delivery_date: '2026-11-16' }, today)).toBe('awaiting_approval')
    expect(orderPhase({ status: 'rejected', delivery_date: '2026-11-10' }, today)).toBe('rejected')
    expect(orderPhase({ status: 'withdrawn', delivery_date: '2026-11-16' }, today)).toBe('withdrawn')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-17' }, today)).toBe('approved')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-16' }, today)).toBe('shipping')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-15' }, today)).toBe('completed')
  })
})
import type { AgentEvent, Order } from './types'

let id = 0
const quote = (quote_id: string, total_eur: number) => ({ quote_id, lines: [{ product_id: '464201' }], total_eur })
const quoteSet = {
  status: 'ok',
  set_id: 'qs_1',
  options: [
    { rank: 1, label: 'best', trade_off: 'Cheapest on time.', quote: quote('q_1', 1010) },
    { rank: 2, label: 'better', trade_off: 'Skimmed.', quote: quote('q_2', 1100) },
  ],
  not_offered: [],
}
const alternatives = [{ quote_id: 'q_3', rank: 3, label: 'good', summary: '40 × 1 L milk (40 L)', total_eur: 60 }]
const ev = (kind: string, extra: Partial<AgentEvent> = {}): AgentEvent => ({
  id: ++id,
  kind,
  run_id: 'r1',
  buyer: 'hotel',
  ...extra,
})

describe('runView', () => {
  it('walks the agent steps and stops at the server decision', () => {
    const events = [
      ev('scene', { title: '1 · The everyday order' }),
      ev('run_start', { request: 'I need 1,000 L' }),
      ev('tool_call', { tool: 'search_products' }),
      ev('tool_call', { tool: 'request_quote' }),
      ev('tool_result', { tool: 'request_quote', result: quoteSet }),
      ev('tool_call', { tool: 'place_order', args: { quote_id: 'q_2' } }),
      ev('decision', { status: 'pending_approval', reasons: ['Over the €800 line limit.'], alternatives }),
      ev('waiting'),
    ]
    const v = runView(events)
    expect(v.scene?.title).toBe('1 · The everyday order')
    expect(v.quote?.quote_id).toBe('q_2') // the option that was ordered, not the first one
    expect(v.steps.map((s) => s.state)).toEqual(['done', 'done', 'done', 'active'])
    expect(v.steps[2].detail).toBe('Over the €800 line limit.')
    expect(v.decision?.status).toBe('pending_approval')
    expect(v.decision?.alternatives).toEqual(alternatives)
  })

  it('shows the best option once quoted, and says when nothing could be offered', () => {
    const quotedOnly = runView([ev('run_start'), ev('tool_result', { tool: 'request_quote', result: quoteSet })])
    expect(quotedOnly.quote?.quote_id).toBe('q_1')
    expect(quotedOnly.steps[1].detail).toBe('2 signed options, valid 15 minutes.')
    const none = runView([ev('run_start'), ev('tool_result', { tool: 'request_quote', result: { status: 'ok', options: [] } })])
    expect(none.quote).toBeNull()
    expect(none.steps[1].detail).toContain('Nothing could be offered')
  })

  it('stops the quote step with the reason when a run ends with nothing offered', () => {
    const empty = {
      status: 'ok',
      options: [],
      not_offered: [{ product_id: '474686', name: 'Oat drink', reason: 'Whether Oat drink contains AN is unknown.' }],
    }
    const v = runView([
      ev('run_start'),
      ev('tool_call', { tool: 'request_quote' }),
      ev('tool_result', { tool: 'request_quote', result: empty }),
      ev('tool_call', { tool: 'search_products' }),
      ev('run_end'),
    ])
    expect(v.steps.map((s) => s.state)).toEqual(['done', 'stopped', 'todo', 'todo'])
    expect(v.steps[1].detail).toBe('Nothing could be offered: Whether Oat drink contains AN is unknown.')
  })

  it('closes the quote step when a run ends after options but no order', () => {
    const v = runView([
      ev('run_start'),
      ev('tool_call', { tool: 'request_quote' }),
      ev('tool_result', { tool: 'request_quote', result: quoteSet }),
      ev('run_end'),
    ])
    expect(v.steps.map((s) => s.state)).toEqual(['done', 'done', 'todo', 'todo'])
  })

  it('marks the buyer’s answer as done, and a run that ends without an order as no order', () => {
    const v = runView([
      ev('run_start'),
      ev('ask', { question: 'Shell or liquid eggs?' }),
      ev('answer', { text: 'whole shell eggs, 200 eggs' }),
      ev('tool_call', { tool: 'search_products' }),
      ev('run_end'),
    ])
    expect(v.steps.map((s) => s.state)).toEqual(['done', 'todo', 'todo', 'done'])
    expect(v.steps[3].detail).toBe('Buyer answered: “whole shell eggs, 200 eggs”')
    expect(v.decision?.status).toBe('no_order')
  })

  it('stops an unanswered question when the run ends, but keeps a pending approval open', () => {
    const unanswered = runView([ev('run_start'), ev('ask', { question: 'Shell or liquid?' }), ev('run_end')])
    expect(unanswered.steps[3].state).toBe('stopped')
    const waiting = runView([
      ev('run_start'),
      ev('tool_call', { tool: 'place_order' }),
      ev('decision', { status: 'pending_approval', reasons: ['Over the limit.'] }),
      ev('run_end'),
    ])
    expect(waiting.steps[3].state).toBe('active')
    expect(waiting.decision?.status).toBe('pending_approval')
  })

  it('shows a person rejecting as stopped and the run as rejected', () => {
    const v = runView([
      ev('run_start'),
      ev('tool_call', { tool: 'place_order' }),
      ev('decision', { status: 'pending_approval', reasons: ['x'] }),
      ev('decision', { status: 'rejected', decided_by: 'boss@x' }),
    ])
    expect(v.steps[3].state).toBe('stopped')
    expect(v.decision?.status).toBe('rejected')
  })

  it('only looks at the latest run', () => {
    const v = runView([
      ev('run_start', { run_id: 'old' }),
      ev('decision', { run_id: 'old', status: 'confirmed', reasons: [] }),
      ev('run_start', { run_id: 'new' }),
    ])
    expect(v.decision).toBeNull()
    expect(v.steps[0].state).toBe('active')
  })
})

const order = (over: Partial<Order> = {}): Order => ({
  order_id: 'ord_1',
  quote_id: 'q_1',
  status: 'confirmed',
  created_at: '2026-11-14T09:00:00Z',
  rationale: 'Cheapest',
  reasons: [],
  total_eur: 10,
  total_with_tax_eur: 11,
  lines: [],
  expires_at: null,
  delivery_date: '2026-11-16',
  approval: null,
  log: [],
  ...over,
})

describe('orderSteps', () => {
  const today = new Date('2026-11-14T12:00:00Z')

  it('confirmed within mandate: approval skipped, delivery upcoming', () => {
    const s = orderSteps(order(), today)
    expect(s.map((x) => x.state)).toEqual(['done', 'done', 'skipped', 'done', 'active'])
    expect(s[4].detail).toContain('2026-11-16')
  })

  it('pending approval keeps the order and delivery open', () => {
    const s = orderSteps(
      order({
        status: 'pending_approval',
        approval: { approval_id: 'a', status: 'pending', approvers: ['m@x'], decided_by: null, decided_at: null },
      }),
      today,
    )
    expect(s.map((x) => x.state)).toEqual(['done', 'done', 'active', 'todo', 'todo'])
  })

  it('rejected by a hard rule stops at the rules step', () => {
    const s = orderSteps(order({ status: 'rejected' }), today)
    expect(s[1].state).toBe('stopped')
    expect(s[3].state).toBe('stopped')
    expect(s[4].detail).toBe('No delivery.')
  })

  it('withdrawn: replaced by another option, neither stopped nor sent', () => {
    const s = orderSteps(
      order({
        status: 'withdrawn',
        approval: { approval_id: 'a', status: 'withdrawn', approvers: ['m@x'], decided_by: 'agent-1', decided_at: '2026-11-14T10:00:00Z' },
      }),
      today,
    )
    expect(s.map((x) => x.state)).toEqual(['done', 'done', 'skipped', 'skipped', 'todo'])
    expect(s[2].detail).toContain('another option')
    expect(s[4].detail).toBe('No delivery.')
  })

  it('never claims a delivery before its date', () => {
    expect(orderSteps(order(), today)[4].state).toBe('active')
    expect(orderSteps(order(), new Date('2026-11-20T00:00:00Z'))[4].state).toBe('done')
  })
})
