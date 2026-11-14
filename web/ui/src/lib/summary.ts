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
      if (r.status === "needs_clarification") return { text: `Valio Aimo asks: ${r.question ?? ""}`, error: false }
      const items = list(result, "products")
      const dropped = list(r.dropped, "dropped")
      const names = items.slice(0, 3).map((p) => String(p.name_en ?? p.name_fi ?? p.id ?? ""))
      return {
        text: `${items.length} fit, ${dropped.length} dropped by ${r.screened_by ?? "the server"} · ${names.join(" · ")}${items.length > 3 ? " …" : ""}`,
        error: false,
      }
    }
    case "get_product":
      return { text: `${r.id ?? ""} ${r.name_en ?? ""}`.trim(), error: false }
    case "request_quote": {
      if (r.status === "needs_clarification") return { text: `Valio Aimo asks: ${r.question ?? ""}`, error: false }
      const options = list(r.options, "options")
      if (!options.length) return { text: `no options · ${list(r.not_offered, "not_offered").length} left out`, error: false }
      const quote = asObj(options[0].quote)
      const lines = list(quote.lines, "lines").map(
        (l) => `${num(l.units)} × ${l.sales_unit ?? "unit"} ${l.name ?? ""} (${num(l.covers)} ${l.content_unit ?? ""})`,
      )
      return { text: `${options.length} options · best ${eur(quote.total_eur)} — ${lines.join(" + ")}`, error: false }
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
