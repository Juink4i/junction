import { eur, num, short } from "./format"

// One line that says what a tool call returned, next to the call in the chat.

type Obj = Record<string, unknown>
const asObj = (v: unknown): Obj => (v && typeof v === "object" ? (v as Obj) : {})
const list = (v: unknown, key: string): Obj[] =>
  (Array.isArray(v) ? v : Array.isArray(asObj(v)[key]) ? (asObj(v)[key] as unknown[]) : []).map(asObj)

export function resultSummary(tool: string | undefined, result: unknown): { text: string; error: boolean } {
  const r = asObj(result)
  const err = asObj(r.error)
  if (r.error) return { text: `${err.code ?? "error"}: ${err.message ?? short(r.error)}`, error: true }
  switch (tool) {
    case "search_products": {
      const items = list(result, "products")
      const names = items.slice(0, 3).map((p) => String(p.name_en ?? p.name_fi ?? p.id ?? ""))
      return { text: `${items.length} products · ${names.join(" · ")}${items.length > 3 ? " …" : ""}`, error: false }
    }
    case "get_product":
      return { text: `${r.id ?? ""} ${r.name_en ?? ""}`.trim(), error: false }
    case "request_quote": {
      const lines = list(r.lines, "lines").map(
        (l) =>
          `${num(l.units)} × ${l.sales_unit ?? "unit"} ${l.name ?? ""} (${num(l.covers)} ${l.content_unit ?? ""}) ${eur(l.line_total_eur)}${l.cutoff_passed ? " · cut-off passed" : ""}`,
      )
      return { text: `quote ${r.quote_id ?? ""} · ${eur(r.total_eur)} — ${lines.join("; ")}`, error: false }
    }
    case "place_order":
      return { text: String(r.status ?? short(result)), error: false }
    case "get_approval_status":
      return { text: `${r.status ?? ""}${r.decided_by ? " by " + r.decided_by : ""}`, error: false }
    case "get_audit_log":
      return { text: `${list(result, "entries").length} log entries`, error: false }
    default:
      return { text: short(result), error: false }
  }
}
