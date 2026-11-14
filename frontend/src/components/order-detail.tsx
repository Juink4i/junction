import { ArrowLeft, CheckCircle2, CircleHelp, Clock, Hourglass, Leaf, OctagonX, Quote, Truck } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router'
import { AllergenChips, ErrorNote, LineTags, TagChips } from '@/components/common'
import { LogTimeline } from '@/components/log-timeline'
import { StepDetails, Stepper } from '@/components/stepper'
import { StatusBadge } from '@/components/status'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { usePoll } from '@/lib/api'
import { eur, num, pct, shortDate, shortId, unitsBothWays } from '@/lib/format'
import { orderSteps, type Step } from '@/lib/pipeline'
import type { Order } from '@/lib/types'
import { cn } from '@/lib/utils'

function heading(o: Order): { banner: string; sub: string; title: string; tone: 'go' | 'wait' | 'ask' | 'stop'; icon: typeof CheckCircle2 } {
  switch (o.status) {
    case 'confirmed':
      return { banner: 'Order confirmed', sub: 'Within the rules, or approved by a person. Sent to Valio Aimo.', title: 'Delivery scheduled', tone: 'go', icon: CheckCircle2 }
    case 'pending_approval':
      return { banner: 'Waiting for approval', sub: 'The server held this order for a person.', title: 'Not sent yet', tone: 'wait', icon: Hourglass }
    case 'needs_clarification':
      return { banner: 'Needs the buyer to confirm', sub: o.question ?? 'The amount looks unusual.', title: 'Not sent yet', tone: 'ask', icon: CircleHelp }
    default:
      return { banner: 'Order rejected', sub: 'A rule was broken or a person said no. Nobody can override.', title: 'No delivery', tone: 'stop', icon: OctagonX }
  }
}

const TONE = {
  go: 'border-go/30 bg-go-soft text-go',
  wait: 'border-wait/30 bg-wait-soft text-wait',
  ask: 'border-ask/30 bg-ask-soft text-ask',
  stop: 'border-stop/30 bg-stop-soft text-stop',
}

/**
 * One order's delivery progress. `apiPath` is the account-scoped URL in the client view
 * or the admin URL in the operations view; `withTrail` adds the hash-chained log rows.
 */
export function OrderDetail({ apiPath, backTo, backLabel, withTrail }: { apiPath: string | null; backTo: string; backLabel: string; withTrail?: boolean }) {
  const { data: o, error, loading, reload } = usePoll<Order & { buyer_name?: string }>(apiPath, 4000)
  const steps = useMemo(() => (o ? orderSteps(o) : []), [o])
  const BackLink = () => (
    <Link to={backTo} className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" /> {backLabel}
    </Link>
  )

  if (loading && !o) return <Skeleton className="h-96 w-full rounded-lg" />
  if (!o)
    return (
      <div className="space-y-3">
        <BackLink />
        <ErrorNote error={error} onRetry={reload} />
      </div>
    )

  const h = heading(o)
  const Icon = h.icon
  const detailFor = (s: Step) =>
    s.key === 'delivery' && o.status === 'confirmed' && o.delivery_date ? `Arrives ${shortDate(o.delivery_date)}` : null
  const reliabilities = o.lines.map((l) => l.product?.delivery_reliability).filter((x): x is number => x != null)
  const worstReliability = reliabilities.length ? Math.min(...reliabilities) : null

  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <BackLink />

      {/* Status banner */}
      <div className={cn('flex items-center gap-3 rounded-xl border p-4', TONE[h.tone])} role="status">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-full bg-card">
          <Icon className="size-6" aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-base font-semibold sm:text-lg">{h.banner}</div>
          <div className="text-sm text-foreground/75">
            {o.buyer_name ? <span className="font-medium">{o.buyer_name} · </span> : null}
            {h.sub}
          </div>
        </div>
        <span className="ml-auto hidden font-mono text-xs text-foreground/60 sm:block">{shortId(o.order_id)}</span>
      </div>

      {/* Delivery progress: dots joined by a line */}
      <Card className="gap-5 p-5 sm:p-7">
        <div className="text-center">
          <h1 className="text-[22px] font-semibold tracking-tight text-emphasis sm:text-[26px]">{h.title}</h1>
          <p className="mt-1 inline-flex items-center gap-1.5 text-sm text-muted-foreground">
            <Clock className="size-4" aria-hidden />
            {o.status === 'confirmed' && o.delivery_date ? (
              <>
                Delivery date: <span className="font-semibold text-go">{shortDate(o.delivery_date)}</span>
              </>
            ) : (
              <>Ordered {shortDate(o.created_at)}</>
            )}
          </p>
        </div>
        <Stepper steps={steps} detailFor={detailFor} />
        <StepDetails steps={steps} detailFor={detailFor} />
        {o.status === 'confirmed' && worstReliability != null && (
          <div className="flex items-center gap-2 rounded-lg bg-go-soft/60 px-3 py-2 text-xs text-foreground/80">
            <Truck className="size-4 shrink-0 text-go" aria-hidden />
            Valio Aimo has delivered {o.lines.length === 1 ? 'this product' : 'these products'} in full {pct(worstReliability)} of the time
            {o.lines.length > 1 ? ' (lowest line)' : ''}. There is no live tracking: the date is Valio Aimo’s promised delivery date.
          </div>
        )}
      </Card>

      <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_320px]">
        {/* Order summary */}
        <Card className="gap-0 p-0">
          <CardHeader className="flex flex-row items-center border-b py-3!">
            <CardTitle className="text-base">Order summary</CardTitle>
            <StatusBadge status={o.status} className="ml-auto" />
          </CardHeader>
          <CardContent className="divide-y p-0">
            {o.lines.map((l) => (
              <div key={l.product_id} className="space-y-1.5 px-5 py-4">
                <div className="flex gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{l.name}</div>
                    <div className="text-xs text-muted-foreground tnum">
                      {unitsBothWays(l)} · {eur(l.unit_price_eur)} per unit · id {l.product_id}
                    </div>
                  </div>
                  <div className="text-right text-sm font-semibold tnum">{eur(l.line_total_eur)}</div>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span>Arrives {shortDate(l.available_date)}</span>
                  <LineTags line={l} />
                </div>
                {l.product && (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                    {l.product.tags && l.product.tags.length > 0 && <TagChips tags={l.product.tags.slice(0, 4)} />}
                    {l.product.allergens_contains && l.product.allergens_contains.length > 0 && (
                      <span className="inline-flex items-center gap-1">
                        Contains <AllergenChips codes={l.product.allergens_contains} tone="stop" />
                      </span>
                    )}
                    {l.product.delivery_reliability != null && (
                      <span className="inline-flex items-center gap-1">
                        <Truck className="size-3" aria-hidden /> full delivery {pct(l.product.delivery_reliability)}
                      </span>
                    )}
                    {l.product.carbon_kg_per_kg != null && (
                      <span className="inline-flex items-center gap-1">
                        <Leaf className="size-3" aria-hidden /> {num(l.product.carbon_kg_per_kg)} kg CO₂e/kg (group average)
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div className="space-y-1 bg-muted/30 px-5 py-4 text-sm tnum">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Total without VAT</span>
                <span className="font-semibold">{eur(o.total_eur)}</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Incl. VAT</span>
                <span>{eur(o.total_with_tax_eur)}</span>
              </div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-5">
          <Card className="gap-3 p-5">
            <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Server’s reasons</div>
            {o.reasons.length ? (
              <ul className="space-y-1.5 pl-4 text-sm">
                {o.reasons.map((r, i) => (
                  <li key={i} className="list-disc">
                    {r}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">Within every rule of the mandate.</p>
            )}
            {o.question && <div className="rounded-md border border-ask/25 bg-ask-soft p-2 text-sm">{o.question}</div>}
          </Card>
          {o.rationale && (
            <Card className="gap-2 p-5">
              <div className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">Agent’s reason</div>
              <p className="flex gap-2 text-sm text-foreground/80">
                <Quote className="mt-0.5 size-3.5 shrink-0" aria-hidden />“{o.rationale}”
              </p>
            </Card>
          )}
        </div>
      </div>

      {withTrail && (
        <Card className="gap-0 p-0">
          <CardHeader className="border-b py-3!">
            <CardTitle className="text-base">Decision trail for this order</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <LogTimeline entries={o.log ?? []} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
