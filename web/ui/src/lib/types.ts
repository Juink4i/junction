// Shapes of what the pages read. Fields are optional on purpose: the trade server and the
// fake server differ a little, and a missing field must never break a page.

export type Status =
  | "confirmed"
  | "approved"
  | "pending_approval"
  | "pending"
  | "needs_clarification"
  | "rejected"

export interface QuoteLine {
  product_id?: string
  name?: string
  units?: number
  sales_unit?: string
  covers?: number
  content_unit?: string
  line_total_eur?: number
  available_date?: string
  cutoff_passed?: boolean
}

export interface Approval {
  approval_id?: string
  id?: string
  status?: string
  buyer?: string
  buyer_name?: string
  mandate?: { buyer?: string }
  total_eur?: number
  need_by?: string
  reasons?: string[]
  rationale?: string
  agent_rationale?: string
  lines?: QuoteLine[]
  quote?: { lines?: QuoteLine[]; total_eur?: number; need_by?: string }
  created_at?: string
  time?: string
  approver?: string
  decided_by?: string | null
}

export interface LogEntry {
  seq: number
  time?: string
  actor?: string
  action?: string
  reason?: string
  prev_hash?: string
  hash?: string
}

export interface Verdict {
  ok: boolean
  broken_at_seq?: number | null
}

export interface Sentence {
  kind: "rule" | "preference" | string
  text: string
}

export interface OptionCard {
  label?: string
  product_id?: string
  name?: string
  units?: number | null
  sales_unit?: string | null
  covers?: number | null
  content_unit?: string | null
  total_eur?: number | null
  available_date?: string | null
  trade_off?: string
  delivery_reliability?: number | null
  carbon_kg_per_kg?: number | null
}

/** One event from the agent, the demo runner or the web server. */
export interface AgentEvent {
  id?: number
  kind: string
  ts?: string
  run_id?: string
  buyer?: string | null
  // scene
  title?: string
  subtitle?: string
  key?: string
  onboard?: string | null
  // run_start
  buyer_name?: string
  model?: string
  request?: unknown
  gullible?: boolean
  preferences?: string[]
  // user / agent / answer / note
  text?: string
  // tool_call / tool_result
  tool?: string
  args?: unknown
  call_id?: string
  result?: unknown
  ok?: boolean | null
  // options
  options?: OptionCard[]
  // ask
  question?: string | null
  // waiting / decision
  approval_id?: string | null
  status?: string
  reasons?: string[]
  decided_by?: string | null
  order_id?: string | null
  quote_id?: string | null
  // verify
  broken_at_seq?: number | null
  count?: number
  // onboarded
  sentences?: Sentence[]
  // run_end
  outcome?: string
  summary?: string
  error?: string | null
}

export interface ShoppingRequest {
  product?: string
  amount?: number
  unit?: string
  need_by?: string
  must_have?: string[]
  avoid?: string[]
  notes?: string
}
