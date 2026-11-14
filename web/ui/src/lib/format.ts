// Number, money and date formatting shared by every page.

const isNum = (v: unknown): v is number | string =>
  v !== null && v !== undefined && v !== "" && !Number.isNaN(Number(v))

export const eur = (v: unknown): string =>
  isNum(v)
    ? "€" + Number(v).toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : "—"

export const num = (v: unknown): string =>
  isNum(v) ? Number(v).toLocaleString("en-GB", { maximumFractionDigits: 2 }) : "—"

export function dayLabel(iso: unknown): string {
  if (!iso) return "—"
  const d = new Date(String(iso).slice(0, 10) + "T12:00:00")
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
}

export function clock(iso: unknown): string {
  const d = new Date(String(iso ?? ""))
  if (Number.isNaN(d.getTime())) return String(iso ?? "")
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

export function ago(iso: unknown): string {
  const t = new Date(String(iso ?? "")).getTime()
  if (Number.isNaN(t)) return ""
  const s = Math.max(0, (Date.now() - t) / 1000)
  if (s < 60) return "just now"
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  return `${Math.floor(s / 3600)} h ago`
}

export const short = (o: unknown, max = 160): string => {
  const s = typeof o === "string" ? o : JSON.stringify(o ?? {})
  return s.length > max ? s.slice(0, max - 1) + "…" : s
}
