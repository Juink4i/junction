import { useMemo, useState } from 'react'
import type { AdminOrder } from '@/lib/types'
import { cn } from '@/lib/utils'

interface Bucket {
  key: string
  label: string
  count: number
}

function dayKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Orders placed per day (per hour for a 24 h range). One series: no legend; the title names it. */
export function OrdersChart({ orders, since, hourly }: { orders: AdminOrder[]; since: string | null; hourly: boolean }) {
  const [hover, setHover] = useState<number | null>(null)

  const buckets = useMemo<Bucket[]>(() => {
    const now = new Date()
    const first = since ? new Date(since) : orders.length ? new Date(Math.min(...orders.map((o) => Date.parse(o.created_at)))) : now
    const out: Bucket[] = []
    const index = new Map<string, number>()
    const cursor = new Date(first)
    if (hourly) cursor.setMinutes(0, 0, 0)
    else cursor.setHours(0, 0, 0, 0)
    let guard = 0
    while (cursor <= now && guard++ < 400) {
      const key = hourly ? `${dayKey(cursor)}T${cursor.getHours()}` : dayKey(cursor)
      index.set(key, out.length)
      out.push({
        key,
        label: hourly
          ? cursor.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
          : cursor.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }),
        count: 0,
      })
      if (hourly) cursor.setHours(cursor.getHours() + 1)
      else cursor.setDate(cursor.getDate() + 1)
    }
    for (const o of orders) {
      const d = new Date(o.created_at)
      const key = hourly ? `${dayKey(d)}T${d.getHours()}` : dayKey(d)
      const i = index.get(key)
      if (i != null) out[i].count += 1
    }
    return out
  }, [orders, since, hourly])

  const max = Math.max(1, ...buckets.map((b) => b.count))
  const top = max <= 4 ? max : Math.ceil(max / 4) * 4
  const ticks = [top, Math.round(top / 2), 0]
  const labelEvery = Math.max(1, Math.ceil(buckets.length / 8))

  return (
    <figure className="space-y-2">
      <div className="flex">
        {/* y axis */}
        <div className="relative mr-2 h-40 w-6 shrink-0 text-right text-[10px] text-muted-foreground tnum" aria-hidden>
          {ticks.map((t) => (
            <span key={t} className="absolute right-0 -translate-y-1/2" style={{ top: `${100 - (t / top) * 100}%` }}>
              {t}
            </span>
          ))}
        </div>
        <div className="relative h-40 flex-1">
          {/* recessive gridlines */}
          {ticks.map((t) => (
            <span key={t} className={cn('absolute inset-x-0 border-t', t === 0 ? 'border-border' : 'border-dashed border-border/60')} style={{ top: `${100 - (t / top) * 100}%` }} aria-hidden />
          ))}
          <div className="absolute inset-0 flex items-end gap-[2px]">
            {buckets.map((b, i) => (
              <div
                key={b.key}
                className="group relative flex h-full flex-1 items-end justify-center"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
                aria-hidden
              >
                <span
                  className={cn('w-full max-w-5 rounded-t-[4px] transition-opacity', hover != null && hover !== i ? 'opacity-50' : 'opacity-100')}
                  style={{ height: `${(b.count / top) * 100}%`, minHeight: b.count ? 2 : 0, background: 'var(--chart-1)' }}
                />
                {hover === i && (
                  <span className="pointer-events-none absolute bottom-full z-10 mb-1 rounded-md border bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow-md">
                    <span className="font-semibold tnum">{b.count}</span> {b.count === 1 ? 'order' : 'orders'} · {b.label}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="ml-8 flex gap-[2px] text-[10px] text-muted-foreground" aria-hidden>
        {buckets.map((b, i) => (
          <span key={b.key} className="flex-1 overflow-visible text-center whitespace-nowrap">
            {i % labelEvery === 0 ? b.label : ''}
          </span>
        ))}
      </div>
      <table className="sr-only">
        <caption>Orders placed per {hourly ? 'hour' : 'day'}</caption>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.key}>
              <th>{b.label}</th>
              <td>{b.count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  )
}
