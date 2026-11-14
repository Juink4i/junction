import { ChevronRight, Package } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router'
import { Empty, ErrorNote, PageHeader } from '@/components/common'
import { StatusBadge } from '@/components/status'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, usePoll } from '@/lib/api'
import { dateTime, eur, num, shortDate, shortId, unitsBothWays } from '@/lib/format'
import { orderSteps, statusLabel } from '@/lib/pipeline'
import type { Order } from '@/lib/types'
import { cn } from '@/lib/utils'

const STATUSES = ['confirmed', 'needs_clarification', 'pending_approval', 'rejected'] as const

/** The dots-and-line indicator, small, for a list row. */
function MiniDots({ order }: { order: Order }) {
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

export default function OrdersPage() {
  const { buyerId, account } = useAccount()
  const { data, error, loading, reload } = usePoll<Order[]>(buyerId ? accountPath(buyerId, '/orders') : null, 4000)
  const [filter, setFilter] = useState<string | null>(null)
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const o of data ?? []) c[o.status] = (c[o.status] ?? 0) + 1
    return c
  }, [data])
  const shown = (data ?? []).filter((o) => !filter || o.status === filter)

  return (
    <div>
      <PageHeader eyebrow={account?.name} title="Orders & delivery" sub="Every order this account’s agent placed, with the server’s decision and delivery progress." />

      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {STATUSES.map((s) => (
          <button key={s} onClick={() => setFilter(filter === s ? null : s)} className="text-left" aria-pressed={filter === s}>
            <Card className={cn('gap-2 p-4 transition-colors hover:border-primary/40', filter === s && 'border-primary ring-2 ring-secondary')}>
              <StatusBadge status={s} />
              <div className="text-[26px] leading-none font-semibold text-emphasis tnum">{num(counts[s] ?? 0)}</div>
            </Card>
          </button>
        ))}
      </div>

      <ErrorNote error={error} onRetry={reload} />
      {loading && !data && <Skeleton className="h-40 w-full rounded-lg" />}
      {data && shown.length === 0 && (
        <Empty icon={<Package className="size-6" />} title={filter ? `No ${statusLabel(filter).toLowerCase()} orders` : 'No orders yet'}>
          Orders appear here as soon as the agent places one.
        </Empty>
      )}

      <div className="space-y-3">
        {shown.map((o) => (
          <Link key={o.order_id} to={`/orders/${o.order_id}`} className="block">
            <Card className="gap-3 p-4 transition-colors hover:border-primary/40 sm:p-5">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-sm font-semibold text-emphasis">{shortId(o.order_id)}</span>
                <StatusBadge status={o.status} />
                <span className="text-xs text-muted-foreground">{dateTime(o.created_at)}</span>
                <span className="ml-auto text-right">
                  <span className="block text-lg leading-none font-semibold text-emphasis tnum">{eur(o.total_eur)}</span>
                  <span className="text-[11px] text-muted-foreground tnum">{eur(o.total_with_tax_eur)} incl. VAT</span>
                </span>
              </div>
              <div className="text-sm">
                {o.lines.map((l) => (
                  <div key={l.product_id} className="truncate">
                    <span className="text-muted-foreground tnum">{unitsBothWays(l)}</span> {l.name}
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap items-center gap-3 border-t pt-3 text-xs text-muted-foreground">
                <MiniDots order={o} />
                <span>{o.status === 'confirmed' ? `Arrives ${shortDate(o.delivery_date)}` : statusLabel(o.status)}</span>
                <ChevronRight className="ml-auto size-4" aria-hidden />
              </div>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
