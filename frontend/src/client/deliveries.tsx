import { ChevronRight, Truck } from 'lucide-react'
import { Link } from 'react-router'
import { Empty, ErrorNote } from '@/components/common'
import { StepDetails, Stepper } from '@/components/stepper'
import { StatusBadge } from '@/components/status'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useAccount } from '@/lib/account'
import { accountPath, usePoll } from '@/lib/api'
import { eur, shortDate, shortId, unitsBothWays } from '@/lib/format'
import { deliverySteps, type Step } from '@/lib/pipeline'
import type { Order } from '@/lib/types'

function dateFor(o: Order) {
  return (s: Step) =>
    o.status !== 'confirmed' || !o.delivery_date
      ? null
      : s.key === 'out'
        ? `Planned for ${shortDate(o.delivery_date)}`
        : s.key === 'delivered'
          ? `Expected ${shortDate(o.delivery_date)}`
          : null
}

function DeliveryCard({ o }: { o: Order }) {
  const steps = deliverySteps(o)
  const detailFor = dateFor(o)
  return (
    <Card className="gap-4 p-5">
      <div className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          {o.lines.map((l) => (
            <div key={l.product_id} className="truncate text-sm font-medium">
              <span className="text-muted-foreground tnum">{unitsBothWays(l)}</span> {l.name}
            </div>
          ))}
          <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="font-mono">{shortId(o.order_id)}</span>
            <StatusBadge status={o.status} />
            {o.status === 'confirmed' && o.delivery_date && <span>Arrives {shortDate(o.delivery_date)}</span>}
          </div>
        </div>
        <div className="text-right">
          <div className="text-lg leading-none font-semibold text-emphasis tnum">{eur(o.total_eur)}</div>
          <Link to={`/client/orders/${o.order_id}`} className="mt-1 inline-flex items-center gap-0.5 text-xs font-medium text-primary hover:underline">
            Details <ChevronRight className="size-3.5" />
          </Link>
        </div>
      </div>
      <Stepper steps={steps} detailFor={detailFor} />
      <StepDetails steps={steps} detailFor={detailFor} />
    </Card>
  )
}

/** The buyer's deliveries: each order through confirming, preparing, out for delivery, delivered. */
export default function ClientDeliveries() {
  const { buyerId, account } = useAccount()
  const { data: orders, error, loading, reload } = usePoll<Order[]>(buyerId ? accountPath(buyerId, '/orders') : null, 4000)
  const live = (orders ?? []).filter((o) => o.status !== 'rejected')
  const rejected = (orders ?? []).filter((o) => o.status === 'rejected')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-emphasis">Deliveries</h1>
        <p className="text-sm text-muted-foreground">
          Where {account ? `${account.name}’s` : 'your'} orders are: confirming, preparing, out for delivery, delivered.
        </p>
      </div>
      <ErrorNote error={error} onRetry={reload} />
      {loading && !orders && <Skeleton className="h-48 w-full rounded-lg" />}
      {orders && live.length === 0 && (
        <Empty icon={<Truck className="size-6" />} title="No deliveries yet">
          When your agent places an order, you can follow it here.
        </Empty>
      )}
      <div className="space-y-4">
        {live.map((o) => (
          <DeliveryCard key={o.order_id} o={o} />
        ))}
      </div>
      {rejected.length > 0 && (
        <details className="rounded-lg border bg-white p-4">
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground">Rejected orders ({rejected.length}): no delivery</summary>
          <div className="mt-4 space-y-4">
            {rejected.map((o) => (
              <DeliveryCard key={o.order_id} o={o} />
            ))}
          </div>
        </details>
      )}
      <p className="text-xs text-muted-foreground">
        “Out for delivery” and “Delivered” will light up once Valio Aimo shares tracking. Until then they show the promised delivery date.
      </p>
    </div>
  )
}
