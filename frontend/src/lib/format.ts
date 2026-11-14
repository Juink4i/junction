// Display helpers. No business rules: these only format what the server sent.

const eurFmt = new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' })
const numFmt = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 2 })

export function eur(value: number | null | undefined): string {
  return value == null || Number.isNaN(value) ? '—' : eurFmt.format(value)
}

export function num(value: number | null | undefined): string {
  return value == null ? '—' : numFmt.format(value)
}

// Sales-unit codes seen in the Valio Aimo product file (Finnish abbreviations).
const UNIT_NAMES: Record<string, string> = {
  ST: 'pc',
  KI: 'case',
  KG: 'kg',
  PAK: 'pack',
  BAG: 'bag',
  RAS: 'tub',
  PRK: 'jar',
  BOT: 'bottle',
  SK: 'sack',
  CS: 'case',
  KLE: 'parcel',
  KRT: 'carton',
  KAN: 'canister',
  PAL: 'pallet',
  NIP: 'bundle',
  L: 'L',
}

export function salesUnitName(code: string | null | undefined): string {
  if (!code) return 'unit'
  return UNIT_NAMES[code.toUpperCase()] ?? code.toLowerCase()
}

/** "1,000 × pc (1,000 L)": sales units and what they cover, always both. */
export function unitsBothWays(line: {
  units?: number | null
  sales_unit?: string | null
  covers?: number | null
  content_unit?: string | null
}): string {
  const units = line.units == null ? '?' : num(line.units)
  const covers = line.covers == null ? '' : ` (${num(line.covers)} ${line.content_unit ?? ''})`.replace(' )', ')')
  return `${units} × ${salesUnitName(line.sales_unit)}${covers}`
}

export function shortDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
}

export function timeOf(iso: string | null | undefined): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export function ago(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return ''
  const s = Math.round((now.getTime() - new Date(iso).getTime()) / 1000)
  if (Number.isNaN(s)) return ''
  if (s < 45) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export function shortHash(hash: string | null | undefined): string {
  if (!hash) return '—'
  return hash.length <= 10 ? hash : `${hash.slice(0, 4)}…${hash.slice(-4)}`
}

export function shortId(id: string | null | undefined): string {
  if (!id) return '—'
  const [prefix, rest] = id.includes('_') ? id.split(/_(.+)/) : ['', id]
  return prefix ? `${prefix}_${rest.slice(0, 8)}` : rest.slice(0, 10)
}

export function pct(value: number | null | undefined): string {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

const CATEGORY_NAMES: Record<string, string> = { '10400': 'Milk and sour milk' }
export function categoryName(code: string): string {
  return CATEGORY_NAMES[code] ? `${CATEGORY_NAMES[code]} (${code})` : code
}

// GS1 allergen type codes used in the product file.
const ALLERGEN_NAMES: Record<string, string> = {
  AM: 'Milk',
  ML: 'Lactose',
  AW: 'Gluten',
  UW: 'Wheat',
  NR: 'Rye',
  GB: 'Barley',
  GO: 'Oats',
  AE: 'Eggs',
  AY: 'Soy',
  AF: 'Fish',
  AC: 'Crustaceans',
  UM: 'Molluscs',
  AP: 'Peanuts',
  AN: 'Tree nuts',
  SA: 'Almonds',
  SH: 'Hazelnuts',
  AS: 'Sesame',
  AU: 'Sulphites',
  BC: 'Celery',
  BM: 'Mustard',
  NL: 'Lupin',
}
export function allergenName(code: string): string {
  return ALLERGEN_NAMES[code.toUpperCase()] ?? code
}

export function tagName(tag: string): string {
  return tag
    .replace(/^FREE_FROM_/, '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/^./, (c) => c.toUpperCase())
    .concat(tag.startsWith('FREE_FROM_') ? '-free' : '')
}
