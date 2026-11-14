import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export const RANGES = [
  { key: '24h', label: '24 h', ms: 24 * 3600e3 },
  { key: '7d', label: '7 days', ms: 7 * 86400e3 },
  { key: '30d', label: 'Month', ms: 30 * 86400e3 },
  { key: '90d', label: '90 days', ms: 90 * 86400e3 },
  { key: 'all', label: 'All', ms: 0 },
] as const
export type RangeKey = (typeof RANGES)[number]['key']

interface RangeState {
  range: RangeKey
  setRange: (r: RangeKey) => void
  /** ISO start of the range, or null for "all". Rounded to the minute so polling URLs stay stable. */
  since: string | null
  label: string
}

const Ctx = createContext<RangeState | null>(null)

function read(): RangeKey {
  try {
    const v = localStorage.getItem('tt.ops.range') as RangeKey | null
    if (v && RANGES.some((r) => r.key === v)) return v
  } catch {
    /* ignore */
  }
  return '30d'
}

export function RangeProvider({ children }: { children: ReactNode }) {
  const [range, setRangeState] = useState<RangeKey>(read)
  const setRange = (r: RangeKey) => {
    setRangeState(r)
    try {
      localStorage.setItem('tt.ops.range', r)
    } catch {
      /* ignore */
    }
  }
  const minute = Math.floor(Date.now() / 60000)
  const since = useMemo(() => {
    const r = RANGES.find((x) => x.key === range)!
    return r.ms ? new Date(minute * 60000 - r.ms).toISOString() : null
  }, [range, minute])
  const label = RANGES.find((x) => x.key === range)!.label
  return <Ctx.Provider value={{ range, setRange, since, label }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useRange(): RangeState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useRange outside RangeProvider')
  return v
}

export function RangePicker({ className }: { className?: string }) {
  const { range, setRange } = useRange()
  return (
    <div className={cn('inline-flex rounded-lg border bg-card p-0.5', className)} role="radiogroup" aria-label="Time range">
      {RANGES.map((r) => (
        <button
          key={r.key}
          role="radio"
          aria-checked={range === r.key}
          onClick={() => setRange(r.key)}
          className={cn(
            'rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
            range === r.key ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:text-foreground',
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  )
}
