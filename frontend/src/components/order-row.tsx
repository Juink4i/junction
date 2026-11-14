import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'
import { StatusBadge } from '@/components/status'
import { dateTime, eur, shortDate, shortId, unitsBothWays } from '@/lib/format'
import { orderSteps, statusLabel } from '@/lib/pipeline'
import type { Order } from '@/lib/types'
import { cn } from '@/lib/utils'

/** The dots-and-line delivery indicator, small, for a list row. */
export function MiniDots({ order }: { order: Order }) {
  const steps = orderSteps(order)
  return (
    <div className="flex items-center" aria-label={`Progress: ${steps.map((s) => `${s.title} ${s.state}`).join(', ')}`}>
      {steps.map((s, i) => (
        <span key={s.key} className="flex items-center">
          {i > 0 && (
            <span
              className={cn(
                'h-0.5 w-4 sm:w-6',
                s.state === 'stopped' || steps[i - 1].state === 'stopped'
                  ? 'bg-stop/40'
                  : s.state === 'done' || s.state === 'skipped'
                    ? 'bg-go'
                    : s.state === 'active'
                      ? 'bg-go/40'
                      : 'bg-border',
              )}
            />
          )}
          <span
            className={cn(
              'size-2.5 rounded-full',
              s.state === 'done' && 'bg-go',
              s.state === 'active' && 'bg-go-soft ring-2 ring-go',
              s.state === 'skipped' && 'border border-dashed border-go/60 bg-card',
              s.state === 'todo' && 'border border-border bg-card',
              s.state === 'stopped' && 'bg-stop',
            )}
          />
        </span>
      ))}
    </div>
  )
}

/** One order as a clickable card: id, outcome, lines in both units, total, delivery dots. */
export function OrderRow({ order: o, to, buyerName }: { order: Order; to: string; buyerName?: string }) {
  return (
    <Link to={to} className="block rounded-lg border bg-card p-4 transition-colors hover:border-primary/40 sm:p-5">
      <div className="flex flex-wrap items-center gap-2">
        {buyerName && <span className="text-sm font-semibold text-emphasis">{buyerName}</span>}
        <span className={cn('font-mono text-xs', buyerName ? 'text-muted-foreground' : 'text-sm font-semibold text-emphasis')}>{shortId(o.order_id)}</span>
        <StatusBadge status={o.status} />
        <span className="text-xs text-muted-foreground">{dateTime(o.created_at)}</span>
        <span className="ml-auto text-right">
          <span className="block text-lg leading-none font-semibold text-emphasis tnum">{eur(o.total_eur)}</span>
          <span className="text-[11px] text-muted-foreground tnum">{eur(o.total_with_tax_eur)} incl. VAT</span>
        </span>
      </div>
      <div className="mt-2 text-sm">
        {o.lines.map((l) => (
          <div key={l.product_id} className="truncate">
            <span className="text-muted-foreground tnum">{unitsBothWays(l)}</span> {l.name}
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-3 border-t pt-3 text-xs text-muted-foreground">
        <MiniDots order={o} />
        <span>{o.status === 'confirmed' ? `Arrives ${shortDate(o.delivery_date)}` : statusLabel(o.status)}</span>
        <ChevronRight className="ml-auto size-4" aria-hidden />
      </div>
    </Link>
  )
}
