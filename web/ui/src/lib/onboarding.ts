// What the onboarding page sends (the answers) and what it reads (the options).
// The lists all come from GET /api/onboarding/options, so the page hard-codes none of them.

export interface Choice {
  code: string
  name: string
}

export interface UsualOrder {
  what: string
  category: string
  amount: number | null
  unit: string
  every: string
}

export interface Answers {
  kitchen: { name: string; type: string; approver: string; enrolment_code: string }
  safety: { blocked_allergens: string[]; unknown_allergens: string; must_be: string[] }
  money: {
    allowed_categories: string[]
    max_order_eur: number | null
    budget: { period: string; max_eur: number } | null
    priorities: string[]
  }
  delivery: { days: string[]; pack_size: string }
  usual_orders: UsualOrder[]
  substitution?: { allowed: boolean; max_price_increase_pct: number }
}

export interface Options {
  kitchen_types: Choice[]
  templates: Record<string, Answers>
  allergens: Choice[]
  categories: Choice[]
  tags: Choice[]
  weekdays: Choice[]
  priorities: Choice[]
  pack_sizes: Choice[]
  periods: Choice[]
  unknown_allergens: Choice[]
  delivery_days_side: string
}

export interface Preview {
  problems: string[]
  sentences: { kind: string; text: string }[]
}

export interface SignedUp {
  buyer_id: string
  name: string
  sentences: { kind: string; text: string }[]
}

export const numberOrNull = (text: string): number | null => (text.trim() === "" ? null : Number(text))
