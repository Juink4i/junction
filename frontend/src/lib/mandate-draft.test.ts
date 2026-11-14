import { describe, expect, it } from 'vitest'
import { changesOf, draftOf } from './mandate-draft'
import type { Mandate, OnboardingOptions, Profile } from './types'

const opts = {
  categories: [{ code: '10400', name: 'Milk and sour milk' }, { code: '10401', name: 'Cream' }],
  weekdays: [{ code: 'MON', name: 'Monday' }, { code: 'THU', name: 'Thursday' }],
  priorities: [
    { code: 'price', name: 'the lowest price' },
    { code: 'reliability', name: 'reliable delivery' },
    { code: 'finnish', name: 'Finnish origin' },
    { code: 'sustainability', name: 'sustainability' },
  ],
  pack_sizes: [{ code: 'small', name: 'smaller packs' }, { code: 'large', name: 'bigger packs' }],
} as OnboardingOptions

const mandate: Mandate = {
  mandate_id: 'mnd_aurinko_001',
  buyer: 'Päiväkoti Aurinko',
  agent_id: 'agent-aurinko',
  valid_until: '2027-11-14',
  auto_approve: { max_order_eur: 100, allowed_categories: ['10400'] },
  substitution: { allowed: true, must_keep: ['ORGANIC'], max_price_increase_pct: 10 },
  hard_rules: { blocked_allergens: ['AP'], unknown_allergens: 'human' },
  approvers: ['kitchen.lead@aurinko.example'],
  budget: { period: 'week', max_eur: 150 },
  delivery: { days: ['MON', 'THU'] },
  usual_orders: [{ category: '10400', amount: 40, content_unit: 'L', every: 'week' }],
}

const profile: Profile = {
  buyer_id: 'aurinko',
  name: 'Päiväkoti Aurinko',
  kitchen_type: 'daycare',
  priorities: ['price', 'reliability', 'finnish', 'sustainability'],
  pack_size: 'small',
  usual_orders: [{ what: 'lactose-free milk', amount: 40, unit: 'L', every: 'week' }],
}

describe('mandate draft', () => {
  it('starts with no changes', () => {
    const c = changesOf(mandate, profile, draftOf(mandate, profile), opts)
    expect(c).toEqual({ body: {}, prefs: {}, summary: [] })
  })

  it('reads usual orders from the mandate with their names from the profile', () => {
    expect(draftOf(mandate, profile).usual).toEqual([{ what: 'lactose-free milk', category: '10400', amount: 40, unit: 'L', every: 'week', on: null }])
    expect(draftOf(mandate, null).usual[0].what).toBe('')
  })

  it('sends changed usual orders with their names, in the mandate shape', () => {
    const d = draftOf(mandate, profile)
    d.usual = [{ ...d.usual[0], amount: 60, on: 'THU' }]
    const c = changesOf(mandate, profile, d, opts)
    expect(c.body.usual_orders).toEqual([{ what: 'lactose-free milk', category: '10400', amount: 60, content_unit: 'L', every: 'week', on: 'THU' }])
    expect(c.summary).toEqual(['Usual orders: 60 L of lactose-free milk every week on Thursday'])
  })

  it('sends a rename even when the amounts stay the same', () => {
    const d = draftOf(mandate, profile)
    d.usual[0].what = 'organic milk'
    expect(changesOf(mandate, profile, d, opts).body.usual_orders?.[0].what).toBe('organic milk')
  })

  it('ignores names for a buyer without a profile', () => {
    const d = draftOf(mandate, null)
    d.usual[0].what = 'anything'
    expect(changesOf(mandate, null, d, opts).body).toEqual({})
  })

  it('sends no usual orders as an empty list', () => {
    const d = draftOf(mandate, profile)
    d.usual = []
    const c = changesOf(mandate, profile, d, opts)
    expect(c.body.usual_orders).toEqual([])
    expect(c.summary).toEqual(['Usual orders: none'])
  })

  it('picks categories from a list, none meaning any', () => {
    const d = draftOf(mandate, profile)
    d.categories = []
    const c = changesOf(mandate, profile, d, opts)
    expect(c.body.auto_approve).toEqual({ allowed_categories: null })
    expect(c.summary).toEqual(['Categories: any'])
    d.categories = ['10401', '10400']
    expect(changesOf(mandate, profile, d, opts).summary).toEqual(['Categories: Milk and sour milk, Cream'])
  })

  it('keeps a must-keep tag outside the old short list', () => {
    expect(draftOf(mandate, profile).mustKeep).toEqual(['ORGANIC'])
  })

  it('puts preferences in their own change', () => {
    const d = draftOf(mandate, profile)
    d.priorities = ['finnish', 'price', 'reliability', 'sustainability']
    d.packSize = 'large'
    const c = changesOf(mandate, profile, d, opts)
    expect(c.body).toEqual({})
    expect(c.prefs).toEqual({ priorities: ['finnish', 'price', 'reliability', 'sustainability'], pack_size: 'large' })
    expect(c.summary).toEqual([
      'Prefer Finnish origin, then the lowest price, then reliable delivery, then sustainability',
      'If two products are equally good, prefer bigger packs',
    ])
  })
})
