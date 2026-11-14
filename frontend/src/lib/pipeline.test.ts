import { describe, expect, it } from 'vitest'
import { deliverySteps, orderPhase, orderSteps, runView } from './pipeline'

describe('deliverySteps (the buyer’s four stages)', () => {
  const base = {
    order_id: 'o', quote_id: 'q', created_at: '2026-11-14T09:00:00Z', rationale: '', question: null,
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
  it('waiting on the buyer or a person: still confirming', () => {
    expect(states({ status: 'pending_approval' })).toEqual(['active', 'todo', 'todo', 'todo'])
    expect(states({ status: 'needs_clarification' })).toEqual(['active', 'todo', 'todo', 'todo'])
  })
  it('rejected: stops at confirming', () => {
    expect(states({ status: 'rejected', reasons: ['Category not allowed.'] })).toEqual(['stopped', 'todo', 'todo', 'todo'])
  })
})

describe('orderPhase', () => {
  const today = new Date(2026, 10, 16, 12) // 16 Nov 2026, local time
  it('maps outcomes and delivery dates to phases', () => {
    expect(orderPhase({ status: 'needs_clarification', delivery_date: null }, today)).toBe('awaiting_input')
    expect(orderPhase({ status: 'pending_approval', delivery_date: '2026-11-16' }, today)).toBe('awaiting_approval')
    expect(orderPhase({ status: 'rejected', delivery_date: '2026-11-10' }, today)).toBe('rejected')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-17' }, today)).toBe('approved')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-16' }, today)).toBe('shipping')
    expect(orderPhase({ status: 'confirmed', delivery_date: '2026-11-15' }, today)).toBe('completed')
  })
})
import type { AgentEvent, Order } from './types'

let id = 0
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
      ev('tool_result', {
        tool: 'request_quote',
        result: { quote_id: 'q_1', lines: [], total_eur: 1010 },
      }),
      ev('tool_call', { tool: 'place_order' }),
      ev('decision', { status: 'pending_approval', reasons: ['Over the €800 line limit.'] }),
      ev('waiting'),
    ]
    const v = runView(events)
    expect(v.scene?.title).toBe('1 · The everyday order')
    expect(v.quote?.quote_id).toBe('q_1')
    expect(v.steps.map((s) => s.state)).toEqual(['done', 'done', 'done', 'active'])
    expect(v.steps[2].detail).toBe('Over the €800 line limit.')
    expect(v.decision?.status).toBe('pending_approval')
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
  question: null,
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

  it('never claims a delivery before its date', () => {
    expect(orderSteps(order(), today)[4].state).toBe('active')
    expect(orderSteps(order(), new Date('2026-11-20T00:00:00Z'))[4].state).toBe('done')
  })
})
