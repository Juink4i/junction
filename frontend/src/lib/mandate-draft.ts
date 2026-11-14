// The mandate editor's form state, and the change it sends. The server validates every value again.
import { allergenName, eur, shortDate, tagName } from './format'
import type { Choice, Mandate, MandateChanges, OnboardingOptions, Profile, ProfileChanges, UsualOrder } from './types'

export interface Draft {
  maxOrder: string
  maxLine: string
  /** Empty means any category. */
  categories: string[]
  subsAllowed: boolean
  subsPct: string
  mustKeep: string[]
  blocked: string[]
  unknown: string
  approvers: string
  validUntil: string
  budget: string
  budgetPeriod: string
  days: string[]
  usual: UsualOrder[]
  /** Null for a buyer without a profile (the demo buyers). */
  priorities: string[] | null
  packSize: string | null
  /** Claims to favour; null without a profile. */
  prefer: string[] | null
}

export const draftOf = (m: Mandate, profile: Profile | null): Draft => ({
  maxOrder: String(m.auto_approve.max_order_eur ?? ''),
  maxLine: String(m.auto_approve.max_line_eur ?? ''),
  categories: m.auto_approve.allowed_categories ?? [],
  subsAllowed: m.substitution.allowed,
  subsPct: String(m.substitution.max_price_increase_pct),
  mustKeep: m.substitution.must_keep,
  blocked: m.hard_rules.blocked_allergens,
  unknown: m.hard_rules.unknown_allergens === 'reject' ? 'reject' : 'human',
  approvers: m.approvers.join(', '),
  validUntil: m.valid_until,
  budget: m.budget ? String(m.budget.max_eur) : '',
  budgetPeriod: m.budget?.period ?? 'week',
  days: m.delivery?.days ?? [],
  usual: (m.usual_orders ?? []).map((o, i) => ({
    what: profile?.usual_orders[i]?.what ?? '',
    category: o.category,
    amount: o.amount,
    unit: o.content_unit === 'KG' ? 'KG' : 'L',
    every: o.every,
    on: o.on ?? null,
  })),
  priorities: profile ? profile.priorities : null,
  packSize: profile ? profile.pack_size : null,
  prefer: profile ? (profile.prefer ?? []) : null,
})

const list = (s: string) => s.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean)
const nameIn = (choices: Choice[] | undefined, code: string) => choices?.find((c) => c.code === code)?.name ?? code
/** Codes in the order the options list them, so picking order never counts as a change. */
const inOrder = (codes: string[], choices: Choice[] | undefined) => {
  const order = (choices ?? []).map((c) => c.code)
  return [...codes].sort((x, y) => order.indexOf(x) - order.indexOf(y))
}

type SentOrder = NonNullable<MandateChanges['usual_orders']>[number]

function sentOrders(orders: UsualOrder[], withNames: boolean): SentOrder[] {
  return orders.map((o) => ({
    ...(withNames ? { what: o.what.trim() } : {}),
    category: o.category,
    amount: Number(o.amount),
    content_unit: o.unit,
    every: o.every,
    ...(o.on != null ? { on: o.on } : {}),
  }))
}

function sayOrder(o: SentOrder, opts: OnboardingOptions): string {
  const when = o.on == null ? '' : o.every === 'month' ? ` on day ${o.on}` : ` on ${nameIn(opts.weekdays, String(o.on))}`
  return `${o.amount} ${o.content_unit} of ${o.what || nameIn(opts.categories, o.category)} every ${o.every}${when}`
}

export function changesOf(
  m: Mandate,
  profile: Profile | null,
  d: Draft,
  opts: OnboardingOptions,
): { body: MandateChanges; prefs: ProfileChanges; summary: string[] } {
  const body: MandateChanges = {}
  const prefs: ProfileChanges = {}
  const summary: string[] = []
  const auto: NonNullable<MandateChanges['auto_approve']> = {}
  if (Number(d.maxOrder) !== m.auto_approve.max_order_eur) {
    auto.max_order_eur = Number(d.maxOrder)
    summary.push(`Per order: ${eur(m.auto_approve.max_order_eur)} → ${eur(Number(d.maxOrder))}`)
  }
  if (d.maxLine !== '' && Number(d.maxLine) !== m.auto_approve.max_line_eur) {
    auto.max_line_eur = Number(d.maxLine)
    summary.push(`Per line: ${m.auto_approve.max_line_eur == null ? 'no limit' : eur(m.auto_approve.max_line_eur)} → ${eur(Number(d.maxLine))}`)
  }
  const cats = inOrder(d.categories, opts.categories)
  if (cats.join() !== inOrder(m.auto_approve.allowed_categories ?? [], opts.categories).join()) {
    auto.allowed_categories = cats.length ? cats : null
    summary.push(`Categories: ${cats.length ? cats.map((c) => nameIn(opts.categories, c)).join(', ') : 'any'}`)
  }
  if (Object.keys(auto).length) body.auto_approve = auto

  const subs: NonNullable<MandateChanges['substitution']> = {}
  if (d.subsAllowed !== m.substitution.allowed) {
    subs.allowed = d.subsAllowed
    summary.push(`Substitutes: ${d.subsAllowed ? 'allowed' : 'not allowed'}`)
  }
  if (Number(d.subsPct) !== m.substitution.max_price_increase_pct) {
    subs.max_price_increase_pct = Number(d.subsPct)
    summary.push(`Substitutes may cost up to ${d.subsPct}% more`)
  }
  if (d.mustKeep.join() !== m.substitution.must_keep.join()) {
    subs.must_keep = d.mustKeep
    summary.push(`Every product must be: ${d.mustKeep.map(tagName).join(', ') || 'nothing in particular'}`)
  }
  if (Object.keys(subs).length) body.substitution = subs

  const hard: NonNullable<MandateChanges['hard_rules']> = {}
  if (d.blocked.join() !== m.hard_rules.blocked_allergens.join()) {
    hard.blocked_allergens = d.blocked
    summary.push(`Never buy: ${d.blocked.map(allergenName).join(', ') || 'nothing blocked'}`)
  }
  if (d.unknown !== m.hard_rules.unknown_allergens) {
    hard.unknown_allergens = d.unknown
    summary.push(`Missing allergen info: ${d.unknown === 'reject' ? 'don’t buy' : 'ask first'}`)
  }
  if (Object.keys(hard).length) body.hard_rules = hard

  const budget = d.budget === '' ? null : { period: d.budgetPeriod, max_eur: Number(d.budget) }
  if (JSON.stringify(budget) !== JSON.stringify(m.budget ? { period: m.budget.period, max_eur: m.budget.max_eur } : null)) {
    body.budget = budget
    summary.push(`Budget: ${budget ? `${eur(budget.max_eur)} per ${budget.period}` : 'none'}`)
  }
  const days = inOrder(d.days, opts.weekdays)
  if (days.join() !== (m.delivery?.days ?? []).join()) {
    body.delivery = { days }
    summary.push(`Delivery days: ${days.length ? days.map((x) => nameIn(opts.weekdays, x)).join(', ') : 'any day'}`)
  }

  // Names live only in a profile, so a buyer without one compares amounts alone.
  const named = profile != null
  const usual = sentOrders(d.usual, named)
  const before = sentOrders(draftOf(m, profile).usual, named)
  if (JSON.stringify(usual) !== JSON.stringify(before)) {
    body.usual_orders = usual
    summary.push(`Usual orders: ${usual.length ? usual.map((o) => sayOrder(o, opts)).join('; ') : 'none'}`)
  }

  if (list(d.approvers).join() !== m.approvers.join()) {
    body.approvers = list(d.approvers)
    summary.push(`Approvers: ${list(d.approvers).join(', ')}`)
  }
  if (d.validUntil !== m.valid_until) {
    body.valid_until = d.validUntil
    summary.push(`Valid until ${shortDate(d.validUntil)}`)
  }

  if (profile && d.priorities && d.priorities.join() !== profile.priorities.join()) {
    prefs.priorities = d.priorities
    summary.push(`Prefer ${d.priorities.map((p) => nameIn(opts.priorities, p)).join(', then ')}`)
  }
  if (profile && d.packSize && d.packSize !== profile.pack_size) {
    prefs.pack_size = d.packSize
    summary.push(`If two products are equally good, prefer ${nameIn(opts.pack_sizes, d.packSize)}`)
  }
  if (profile && d.prefer) {
    const prefer = inOrder(d.prefer, opts.prefer_tags)
    if (prefer.join() !== inOrder(profile.prefer ?? [], opts.prefer_tags).join()) {
      prefs.prefer = prefer
      summary.push(prefer.length ? `If two products are equally good, prefer ones that are ${prefer.map((t) => nameIn(opts.prefer_tags, t)).join(', ')}` : 'No preferred properties')
    }
  }
  return { body, prefs, summary }
}
