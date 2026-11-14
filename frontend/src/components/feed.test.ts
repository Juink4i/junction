import { describe, expect, it } from 'vitest'
import { argsSummary, resultSummary } from './feed'

describe('tool call lines in the feed', () => {
  it('summarises the plain-word search and the quote request', () => {
    expect(argsSummary('search_products', { product: 'lactose-free milk', must_have: ['lactose-free'], amount: 1000, unit: 'L' }))
      .toBe('"lactose-free milk" · lactose-free · 1,000 L')
    expect(argsSummary('request_quote', { product_ids: ['464201', '463038'], amount: 1000, unit: 'L', need_by: '2026-11-16' }))
      .toBe('2 products · 1,000 L · by 2026-11-16')
    expect(argsSummary('place_order', { quote_id: 'q_1', rationale: 'x', agent_signature: '[signed]' })).toBe('q_1')
  })

  it('summarises search, quote-set and question results', () => {
    expect(resultSummary('search_products', { status: 'ok', products: [{}, {}], dropped: [{}] })).toBe('2 products · 1 left out')
    expect(resultSummary('request_quote', { status: 'ok', options: [{ quote: { quote_id: 'q_1', total_eur: 1010 } }, { quote: {} }] }))
      .toBe('2 signed options · best €1,010.00')
    expect(resultSummary('request_quote', { status: 'ok', options: [] })).toBe('nothing could be offered')
    expect(resultSummary('search_products', { status: 'needs_clarification', question: 'Which milk?' })).toBe('asks: Which milk?')
  })
})
