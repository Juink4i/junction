// Shapes returned by the web/ backend-for-frontend. Only display data: the server decides.

// 'withdrawn': the agent ordered another option from the same request instead (web/accounts.py).
export type OrderStatus = 'confirmed' | 'pending_approval' | 'rejected' | 'withdrawn'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'withdrawn'

export interface ApiError {
  code: string
  message: string
  retryable?: boolean
}

export interface Mandate {
  mandate_id: string
  buyer: string
  agent_id: string
  valid_until: string
  issued_at?: string
  auto_approve: { max_order_eur?: number; max_line_eur?: number; allowed_categories?: string[] }
  substitution: { allowed: boolean; must_keep: string[]; max_price_increase_pct: number }
  hard_rules: { blocked_allergens: string[]; unknown_allergens: string; no_delivery_after?: string }
  approvers: string[]
  // From onboarding (kitchens that signed up themselves):
  budget?: { period: string; max_eur: number } | null
  delivery?: { days: string[] | null } | null
  usual_orders?: { category: string; amount: number; content_unit: string; every: string; on?: string | number | null }[]
  agent_key?: string
}

export interface Account {
  buyer_id: string
  name: string
  mandate: Mandate | null
  mandate_verified: boolean
  mandate_problem: string | null
}

export interface ProductExtra {
  category: string | null
  tags: string[] | null
  delivery_reliability: number | null
  carbon_kg_per_kg: number | null
  allergen_info_missing: boolean | null
  allergens_contains: string[] | null
}

export interface QuoteLine {
  product_id: string
  name: string
  units: number
  sales_unit: string
  covers: number
  content_unit: string
  unit_price_eur: number
  line_total_eur: number
  available_date: string | null
  cutoff_passed: boolean
  stock: 'confirmed' | 'unconfirmed'
  product?: ProductExtra | null
}

export interface LogEntry {
  seq: number
  time: string
  actor: string
  action: string
  reason: string
  prev_hash: string
  hash: string
  order_id?: string | null
  quote_id?: string | null
}

export interface Order {
  order_id: string
  quote_id: string
  status: OrderStatus
  created_at: string
  rationale: string
  reasons: string[]
  total_eur: number
  total_with_tax_eur: number
  lines: QuoteLine[]
  expires_at: string | null
  delivery_date: string | null
  approval: null | {
    approval_id: string
    status: ApprovalStatus
    approvers: string[]
    decided_by: string | null
    decided_at: string | null
  }
  log?: LogEntry[]
}

export interface PendingApproval {
  approval_id: string
  order_id: string
  quote_id: string
  status: ApprovalStatus
  buyer: string
  approvers: string[]
  reasons: string[]
  agent_rationale: string
  lines: QuoteLine[]
  total_eur: number
  total_with_tax_eur: number
  created_at: string
}

/** Valio Aimo operations view: one row per connected buyer. */
export interface AdminClient {
  buyer_id: string
  name: string
  agent_id: string | null
  mandate_id: string | null
  valid_until: string | null
  mandate_verified: boolean
  mandate_problem: string | null
  last_seen: string | null
  agent_running: boolean
  orders_total: number
}

export interface AdminOrder extends Order {
  buyer_id: string
  buyer_name: string
}

export interface AdminLogEntry extends LogEntry {
  buyer_id: string | null
}

/** The fields a buyer may change in its own mandate (PUT /accounts/{id}/mandate). */
export interface MandateChanges {
  auto_approve?: { max_order_eur?: number; max_line_eur?: number; allowed_categories?: string[] | null }
  substitution?: { allowed?: boolean; must_keep?: string[]; max_price_increase_pct?: number }
  hard_rules?: { blocked_allergens?: string[]; unknown_allergens?: string }
  budget?: { period?: string; max_eur?: number } | null
  delivery?: { days: string[] | null } | null
  approvers?: string[]
  valid_until?: string
  /** Replaces the list. `what` is the plain name, kept in the kitchen's profile. */
  usual_orders?: { what?: string; category: string; amount: number; content_unit: string; every: string; on?: string | number }[]
}

// Shapes from web/ /api/onboarding/options (onboarding/options.py), shared by onboarding and the mandate editor.
export interface Choice {
  code: string
  name: string
  /** Categories only: a few product names, for searching. */
  examples?: string[]
}
export interface UsualOrder {
  what: string
  category: string
  amount: number | null
  unit: 'L' | 'KG'
  every: string
  /** Weekday code for a weekly order, 1-31 for a monthly one; null = any day. */
  on?: string | number | null
}
export interface OnboardingAnswers {
  kitchen: { name: string; type: string; approver: string; enrolment_code: string }
  safety: { blocked_allergens: string[]; unknown_allergens: string; must_be: string[] }
  money: { allowed_categories: string[]; max_order_eur: number | null; budget: { period: string; max_eur: number } | null; priorities: string[] }
  delivery: { days: string[]; pack_size: string }
  usual_orders: UsualOrder[]
  substitution?: { allowed: boolean; max_price_increase_pct: number }
  /** Claims to favour when products are otherwise equal. Never a rule. */
  prefer?: string[]
}
export interface OnboardingOptions {
  kitchen_types: Choice[]
  templates: Record<string, OnboardingAnswers>
  allergens: Choice[]
  categories: Choice[]
  /** What every product must be: only what the server can check. */
  tags: Choice[]
  /** Every other claim, offered as a preference. */
  prefer_tags: Choice[]
  weekdays: Choice[]
  priorities: Choice[]
  pack_sizes: Choice[]
  periods: Choice[]
  unknown_allergens: Choice[]
  month_days: number[]
}

/** A kitchen's preferences from onboarding (GET /accounts/{id}/profile). Only its agent reads them. */
export interface Profile {
  buyer_id: string
  name: string
  kitchen_type: string
  priorities: string[]
  pack_size: string
  prefer?: string[]
  usual_orders: { what: string; amount: number; unit: string; every: string; on?: string | number | null }[]
}
export type ProfileChanges = Partial<Pick<Profile, 'priorities' | 'pack_size' | 'prefer'>>

export interface VerifyResult {
  ok: boolean
  broken_at_seq?: number | null
}

export interface OptionCard {
  label: string
  product_id: string
  name: string
  units?: number | null
  sales_unit?: string | null
  covers?: number | null
  content_unit?: string | null
  total_eur?: number | null
  available_date?: string | null
  trade_off: string
  delivery_reliability?: number | null
  carbon_kg_per_kg?: number | null
}

/** Another option from the same request that would go through without a person. */
export interface Alternative {
  quote_id: string
  rank: number
  label: string
  summary: string
  total_eur: number
}

/** One agent event from /api/events/stream (agent/events.py). */
export interface AgentEvent {
  id: number
  kind: string
  ts?: string
  run_id?: string
  buyer?: string | null
  // kind-specific fields
  text?: string
  tool?: string
  args?: Record<string, unknown>
  call_id?: string
  result?: unknown
  ok?: boolean
  title?: string
  subtitle?: string
  key?: string
  options?: OptionCard[]
  status?: string
  reasons?: string[]
  alternatives?: Alternative[]
  question?: string | null
  approval_id?: string | null
  order_id?: string | null
  quote_id?: string | null
  decided_by?: string | null
  request?: Record<string, unknown> | string
  buyer_name?: string
  model?: string
  outcome?: string | null
  summary?: string | null
  error?: string | null
  wait_s?: number
  broken_at_seq?: number | null
  count?: number
}
