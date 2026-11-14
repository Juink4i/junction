// Shapes returned by the web/ backend-for-frontend. Only display data: the server decides.

export type OrderStatus = 'confirmed' | 'needs_clarification' | 'pending_approval' | 'rejected'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected'

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
  auto_approve: { max_order_eur?: number; max_line_eur?: number; allowed_categories?: string[] }
  substitution: { allowed: boolean; must_keep: string[]; max_price_increase_pct: number }
  hard_rules: { blocked_allergens: string[]; unknown_allergens: string; no_delivery_after?: string }
  approvers: string[]
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
  question: string | null
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
